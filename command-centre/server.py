#!/usr/bin/env python3
"""BRO local-first command center MVP. Python standard library only."""
from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from core.routing import classify
from core.debate import review as debate_review
from core.safety import action_policy
from core.adversarial.providers import ModelProvider, load_models, load_providers

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
DB_PATH = Path(os.environ.get("BRO_DB_PATH", ROOT / "data" / "bro.db"))
HOST = os.environ.get("BRO_HOST", "127.0.0.1")
PORT = int(os.environ.get("BRO_PORT", "8787"))
OLLAMA_MODEL = os.environ.get("BRO_OLLAMA_MODEL", "").strip()
OLLAMA_URL = os.environ.get("BRO_OLLAMA_URL", "http://127.0.0.1:11434/api/chat")
DEBATE_PROVIDERS = load_providers(ollama_model=OLLAMA_MODEL, ollama_url=OLLAMA_URL)
MODEL_PROVIDERS = load_models(ollama_model=OLLAMA_MODEL, ollama_url=OLLAMA_URL)
MODEL_BY_ID = {provider.id: provider for provider in MODEL_PROVIDERS}
DEFAULT_MODEL_ID = next((provider.id for provider in MODEL_PROVIDERS if provider.public_view()["ready"]), "")
DB_LOCK = threading.RLock()


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    return db


def init_db() -> None:
    with DB_LOCK, connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS tasks (
          id TEXT PRIMARY KEY, title TEXT NOT NULL, prompt TEXT NOT NULL,
          status TEXT NOT NULL, risk TEXT NOT NULL DEFAULT 'low',
          mode TEXT NOT NULL DEFAULT 'local-demo', result TEXT,
          decision_json TEXT, debate_json TEXT,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, kind TEXT NOT NULL,
          actor TEXT NOT NULL, message TEXT NOT NULL, created_at TEXT NOT NULL,
          FOREIGN KEY(task_id) REFERENCES tasks(id)
        );
        CREATE TABLE IF NOT EXISTS approvals (
          id TEXT PRIMARY KEY, task_id TEXT NOT NULL, action TEXT NOT NULL,
          rationale TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
          created_at TEXT NOT NULL, decided_at TEXT,
          FOREIGN KEY(task_id) REFERENCES tasks(id)
        );
        CREATE TABLE IF NOT EXISTS memory (
          id INTEGER PRIMARY KEY AUTOINCREMENT, layer TEXT NOT NULL,
          content TEXT NOT NULL, source_task TEXT, confidence REAL NOT NULL DEFAULT 0.0,
          created_at TEXT NOT NULL, valid_until TEXT,
          FOREIGN KEY(source_task) REFERENCES tasks(id)
        );
        """)
        # Preserve databases created by the earlier MVP archive.
        columns={row[1] for row in db.execute("PRAGMA table_info(tasks)")}
        for name in ("decision_json", "debate_json"):
            if name not in columns:
                db.execute(f"ALTER TABLE tasks ADD COLUMN {name} TEXT")


def log_event(db: sqlite3.Connection, task_id: str | None, kind: str, actor: str, message: str) -> None:
    db.execute("INSERT INTO events(task_id,kind,actor,message,created_at) VALUES(?,?,?,?,?)",
               (task_id, kind, actor, message, now()))


def task_risk(prompt: str) -> str:
    return "approval" if classify(prompt, bool(OLLAMA_MODEL)).requires_human_approval else "low"


def title_from(prompt: str) -> str:
    clean = re.sub(r"\s+", " ", prompt).strip()
    return clean[:64] + ("…" if len(clean) > 64 else "")


def model_chat(system: str, prompt: str, model_id: str = "") -> str | None:
    provider = MODEL_BY_ID.get(model_id or DEFAULT_MODEL_ID)
    if not provider or not provider.public_view()["ready"]:
        return None
    try:
        return provider.complete(system, prompt, structured=False)
    except (RuntimeError, OSError, urllib.error.URLError, json.JSONDecodeError, TimeoutError):
        return None


def run_workflow(task_id: str) -> None:
    try:
        with DB_LOCK, connect() as db:
            row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not row or row["status"] != "queued":
                return
            prompt = row["prompt"]
            risk = row["risk"]
            selected_model_id = row["mode"].removeprefix("model:") if row["mode"].startswith("model:") else ""
            decision = classify(prompt, bool(OLLAMA_MODEL or DEBATE_PROVIDERS))
            db.execute("UPDATE tasks SET status='running', updated_at=? WHERE id=?", (now(), task_id))
            log_event(db, task_id, "status", "BRO", "Task entered the local agent workflow.")

        mode = "model:" + selected_model_id if selected_model_id else "local-demo"
        with DB_LOCK, connect() as db:
            db.execute("UPDATE tasks SET mode=? WHERE id=?", (mode, task_id))
            db.execute("UPDATE tasks SET decision_json=? WHERE id=?", (json.dumps(decision.to_dict()), task_id))
            log_event(db, task_id, "agent", "Coordinator", f"Typed route: {decision.choice}; score {decision.score:.2f}; Noul={decision.noul}; model={decision.model_class}.")

        plan = model_chat("You are BRO's concise task coordinator. Make a safe, short plan. Never claim you executed anything.", prompt, selected_model_id)
        if not plan:
            plan = "Break the request into a small, reviewable result; gather only the context needed; verify the answer before returning it."
        with DB_LOCK, connect() as db:
            log_event(db, task_id, "agent", "Coordinator", plan[:1000])

        answer = model_chat("You are BRO's task worker. Answer helpfully and concisely. Do not claim to have used tools or changed external systems.", prompt, selected_model_id)
        model_generated = bool(answer)
        if not answer:
            answer = demo_answer(prompt)
        with DB_LOCK, connect() as db:
            log_event(db, task_id, "agent", "Worker", answer[:1400])

        debate = debate_review(answer, model_used=model_generated, task=prompt, providers=DEBATE_PROVIDERS)
        critique = debate.challenger_summary
        result = answer + "\n\nVerifier: " + critique
        debate_json = json.dumps(debate.to_dict())
        if risk == "approval":
            action = f"Review requested action: {title_from(prompt)}"
            with DB_LOCK, connect() as db:
                approval_id = uuid.uuid4().hex[:12]
                db.execute("INSERT INTO approvals(id,task_id,action,rationale,status,created_at) VALUES(?,?,?,?,?,?)",
                           (approval_id, task_id, action, "The request appears to change an external system or user data. BRO requires a human decision.", "pending", now()))
                db.execute("UPDATE tasks SET status='review', result=?, debate_json=?, updated_at=? WHERE id=?",
                           (result, debate_json, now(), task_id))
                db.execute("INSERT INTO memory(layer,content,source_task,confidence,created_at) VALUES(?,?,?,?,?)",
                           ("episodic", result[:5000], task_id, debate.confidence, now()))
                log_event(db, task_id, "approval", "Safety Gate", "A proposed action is waiting for explicit human approval. BRO has not executed it.")
        else:
            with DB_LOCK, connect() as db:
                db.execute("UPDATE tasks SET status='complete', result=?, debate_json=?, updated_at=? WHERE id=?",
                           (result, debate_json, now(), task_id))
                db.execute("INSERT INTO memory(layer,content,source_task,confidence,created_at) VALUES(?,?,?,?,?)",
                           ("episodic", result[:5000], task_id, debate.confidence, now()))
                log_event(db, task_id, "status", "BRO", "Local workflow completed; no external action was taken.")
    except Exception as exc:  # Keep one task failure from killing the server.
        with DB_LOCK, connect() as db:
            db.execute("UPDATE tasks SET status='failed', updated_at=? WHERE id=?", (now(), task_id))
            log_event(db, task_id, "error", "BRO", f"Workflow failed safely: {type(exc).__name__}")


def demo_answer(prompt: str) -> str:
    return ("BRO did not get a usable inference response for this task. This is a deterministic local demo response, not output from the selected model. Check the provider endpoint and server-side credentials, or configure BRO_MODELS / BRO_OLLAMA_MODEL.\n\n"
            f"Request received: {prompt[:500]}")


def rows(db: sqlite3.Connection, query: str, args: tuple = ()) -> list[dict]:
    return [dict(row) for row in db.execute(query, args).fetchall()]


class Handler(BaseHTTPRequestHandler):
    server_version = "BRO/0.1"

    def log_message(self, fmt: str, *args) -> None:
        print(f"[{now()}] {self.address_string()} {fmt % args}")

    def send_json(self, code: int, payload: dict | list) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict:
        length = min(int(self.headers.get("Content-Length", "0")), 32_000)
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/health":
            provider_views=[provider.public_view() for provider in DEBATE_PROVIDERS]
            default_provider = MODEL_BY_ID.get(DEFAULT_MODEL_ID)
            self.send_json(200, {"ok": True, "model_configured": bool(default_provider), "model": default_provider.model if default_provider else "Local demo", "storage": "SQLite", "bind": HOST,
                                 "debate_provider_count": len(provider_views), "debate_providers": provider_views,
                                 "model_providers": [provider.public_view() for provider in MODEL_PROVIDERS],
                                 "default_model": DEFAULT_MODEL_ID or None,
                                 "external_data_egress": any(p.trust_domain == "remote" for p in DEBATE_PROVIDERS + MODEL_PROVIDERS)})
        elif path == "/api/models":
            self.send_json(200, {"models": [provider.public_view() for provider in MODEL_PROVIDERS],
                                 "default_model": DEFAULT_MODEL_ID or None})
        elif path == "/api/state":
            with DB_LOCK, connect() as db:
                self.send_json(200, {"tasks": rows(db, "SELECT * FROM tasks ORDER BY created_at DESC LIMIT 40"),
                                     "approvals": rows(db, "SELECT * FROM approvals WHERE status='pending' ORDER BY created_at DESC"),
                                     "events": rows(db, "SELECT * FROM events ORDER BY id DESC LIMIT 30"),
                                     "memory_count": db.execute("SELECT COUNT(*) FROM memory").fetchone()[0]})
        elif path == "/api/memory":
            with DB_LOCK, connect() as db:
                self.send_json(200, {"layers": {"episodic": rows(db, "SELECT * FROM memory WHERE layer='episodic' ORDER BY id DESC LIMIT 50"),
                                                 "working": [], "semantic": []},
                                     "status": {"episodic": "sqlite-active", "working": "in-process-only", "semantic": "not-configured"}})
        elif path.startswith("/api/task/"):
            task_id = path.rsplit("/", 1)[-1]
            with DB_LOCK, connect() as db:
                task = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
                if not task:
                    self.send_json(404, {"error": "Task not found"})
                    return
                self.send_json(200, {"task": dict(task), "events": rows(db, "SELECT * FROM events WHERE task_id=? ORDER BY id", (task_id,))})
        elif path == "/" or path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write((WEB / "index.html").read_bytes())
        else:
            self.send_json(404, {"error": "Not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            data = self.read_json()
        except (ValueError, json.JSONDecodeError):
            self.send_json(400, {"error": "Invalid JSON"})
            return
        if path == "/api/tasks":
            prompt = str(data.get("prompt", "")).strip()
            if not prompt or len(prompt) > 4000:
                self.send_json(400, {"error": "Enter a task between 1 and 4000 characters."})
                return
            requested_model = str(data.get("model_id", "") or "")
            selected_model = MODEL_BY_ID.get(requested_model) if requested_model else MODEL_BY_ID.get(DEFAULT_MODEL_ID)
            if requested_model and not selected_model:
                self.send_json(400, {"error": "That model is not configured on this BRO server."})
                return
            if selected_model and not selected_model.public_view()["ready"]:
                self.send_json(503, {"error": "That model needs a server-side API key before it can be used."})
                return
            task_id, stamp = uuid.uuid4().hex[:12], now()
            policy = action_policy(prompt, bool(selected_model or DEBATE_PROVIDERS))
            route = policy["decision"]
            risk = "approval" if route["requires_human_approval"] else "low"
            with DB_LOCK, connect() as db:
                mode = "model:" + selected_model.id if selected_model else "local-demo"
                db.execute("INSERT INTO tasks(id,title,prompt,status,risk,mode,decision_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                           (task_id, title_from(prompt), prompt, "queued", risk, mode, json.dumps(route), stamp, stamp))
                log_event(db, task_id, "status", "BRO", "Task accepted into the local queue.")
            threading.Thread(target=run_workflow, args=(task_id,), daemon=True).start()
            self.send_json(201, {"id": task_id, "status": "queued", "route": route, "model": selected_model.public_view() if selected_model else None, "execution": policy["execution"]})
        elif path.startswith("/api/approvals/") and path.endswith("/decision"):
            approval_id = path.split("/")[3]
            decision = data.get("decision")
            if decision not in ("approve", "deny"):
                self.send_json(400, {"error": "Decision must be approve or deny."})
                return
            with DB_LOCK, connect() as db:
                approval = db.execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone()
                if not approval or approval["status"] != "pending":
                    self.send_json(404, {"error": "Pending approval not found."})
                    return
                status = "approved" if decision == "approve" else "denied"
                db.execute("UPDATE approvals SET status=?, decided_at=? WHERE id=?", (status, now(), approval_id))
                db.execute("UPDATE tasks SET status=?, updated_at=? WHERE id=?", ("complete" if decision == "approve" else "failed", now(), approval["task_id"]))
                log_event(db, approval["task_id"], "approval", "You", f"You {decision}d the proposal. The current release records consent but runs no tool action.")
            self.send_json(200, {"ok": True, "status": status, "executed": False})
        else:
            self.send_json(404, {"error": "Not found"})


if __name__ == "__main__":
    init_db()
    print(f"BRO is ready at http://{HOST}:{PORT} — storage: {DB_PATH}")
    print("Local demo mode is active." if not MODEL_PROVIDERS else f"{len(MODEL_PROVIDERS)} inference model(s) configured")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
