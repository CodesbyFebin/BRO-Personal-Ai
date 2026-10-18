import json
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

import server
from core.routing import classify
from core.adversarial.providers import ModelProvider, load_models


class RoutingTests(unittest.TestCase):
    def test_simple_request_uses_low_risk_route(self):
        decision = classify("Summarize this note")
        self.assertEqual(decision.choice, "trivial")
        self.assertFalse(decision.requires_human_approval)
        self.assertEqual(decision.noul, "low-risk")

    def test_external_side_effect_requires_human_gate(self):
        decision = classify("Deploy the service to production")
        self.assertTrue(decision.requires_human_approval)
        self.assertEqual(decision.noul, "review")


class CloudModelTests(unittest.TestCase):
    def test_registry_accepts_openai_anthropic_gemini_and_local_models(self):
        models = load_models('[{"id":"oai","protocol":"openai","model":"m","base_url":"https://api.openai.com/v1","trust_domain":"remote","api_key_env":"OPENAI_API_KEY"},'
                            '{"id":"claude","protocol":"anthropic","model":"m","base_url":"https://api.anthropic.com/v1","trust_domain":"remote","api_key_env":"ANTHROPIC_API_KEY"},'
                            '{"id":"gemini","protocol":"gemini","model":"m","base_url":"https://generativelanguage.googleapis.com/v1beta","trust_domain":"remote","api_key_env":"GEMINI_API_KEY"}]')
        self.assertEqual([model.protocol for model in models], ["openai", "anthropic", "gemini"])
        self.assertFalse(models[0].public_view()["ready"])
        self.assertNotIn("api_key_env", models[0].public_view())

    def test_anthropic_adapter_keeps_key_in_header_and_parses_text(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, limit): return b'{"content":[{"type":"text","text":"Cloud answer"}]}'
        model = ModelProvider("claude", "anthropic", "claude-model", "https://api.anthropic.com/v1", "remote", api_key_env="TEST_CLOUD_KEY")
        with patch.dict("os.environ", {"TEST_CLOUD_KEY": "secret-value"}), patch("core.adversarial.providers.urllib.request.urlopen", return_value=Response()) as send:
            self.assertEqual(model.complete("system", "hello"), "Cloud answer")
            request = send.call_args.args[0]
            self.assertEqual(request.get_header("X-api-key"), "secret-value")
            self.assertNotIn("secret-value", request.full_url)
            self.assertNotIn("secret-value", model.public_view().__str__())

    def test_gemini_adapter_parses_generate_content_shape(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, limit): return b'{"candidates":[{"content":{"parts":[{"text":"Gemini answer"}]}}]}'
        model = ModelProvider("gemini", "gemini", "gemini-model", "https://generativelanguage.googleapis.com/v1beta", "remote", api_key_env="TEST_GEMINI_KEY")
        with patch.dict("os.environ", {"TEST_GEMINI_KEY": "secret-value"}), patch("core.adversarial.providers.urllib.request.urlopen", return_value=Response()) as send:
            self.assertEqual(model.complete("system", "hello"), "Gemini answer")
            request = send.call_args.args[0]
            self.assertEqual(request.get_header("X-goog-api-key"), "secret-value")
            self.assertTrue(request.full_url.endswith("/models/gemini-model:generateContent"))


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        server.DB_PATH = Path(cls.tmp.name) / "test.db"
        server.init_db()
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.thread.join(timeout=2)
        cls.httpd.server_close()
        cls.tmp.cleanup()

    def call(self, path, body=None):
        payload = None if body is None else json.dumps(body).encode()
        request = Request(self.base + path, data=payload,
                          headers={"Content-Type": "application/json"} if payload else {})
        with urlopen(request, timeout=4) as response:
            return json.loads(response.read())

    def wait_task(self, task_id):
        for _ in range(40):
            with server.DB_LOCK, server.connect() as db:
                row = db.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()
                if row and row["status"] not in ("queued", "running"):
                    return row["status"]
            time.sleep(.05)
        self.fail("workflow did not reach a terminal state")

    def test_task_completes_and_persists_episode(self):
        created = self.call("/api/tasks", {"prompt": "Summarize a local-first workflow."})
        self.assertEqual(self.wait_task(created["id"]), "complete")
        memory = self.call("/api/memory")
        self.assertGreaterEqual(len(memory["layers"]["episodic"]), 1)
        self.assertEqual(memory["status"]["semantic"], "not-configured")

    def test_mutating_request_waits_for_human_and_does_not_execute(self):
        created = self.call("/api/tasks", {"prompt": "Deploy the service to production."})
        self.assertEqual(self.wait_task(created["id"]), "review")
        state = self.call("/api/state")
        approval = next(a for a in state["approvals"] if a["task_id"] == created["id"])
        decision = self.call(f"/api/approvals/{approval['id']}/decision", {"decision": "approve"})
        self.assertFalse(decision["executed"])

    def test_selected_model_is_bound_to_the_queued_task(self):
        model = ModelProvider("test-cloud", "openai", "test-model", "http://127.0.0.1:9999/v1", "local")
        with patch.dict(server.MODEL_BY_ID, {model.id: model}), patch.object(server, "DEFAULT_MODEL_ID", model.id), patch.object(server, "model_chat", return_value="mock model response"):
            created = self.call("/api/tasks", {"prompt": "Summarize a local-first workflow.", "model_id": "test-cloud"})
            self.assertEqual(created["model"]["id"], "test-cloud")
            self.assertEqual(self.wait_task(created["id"]), "complete")
            details = self.call("/api/task/" + created["id"])
            self.assertEqual(details["task"]["mode"], "model:test-cloud")
            self.assertIn("mock model response", details["task"]["result"])

    def test_unknown_model_is_rejected_before_queueing(self):
        request = Request(self.base + "/api/tasks", data=json.dumps({"prompt": "hello", "model_id": "not-configured"}).encode(),
                          headers={"Content-Type": "application/json"})
        with self.assertRaises(Exception) as error:
            urlopen(request, timeout=4)
        self.assertEqual(getattr(error.exception, "code", None), 400)


if __name__ == "__main__":
    unittest.main()
