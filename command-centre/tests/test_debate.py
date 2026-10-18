import json
import unittest

from core.adversarial.debate import aggregate, conduct, parse_vote
from core.adversarial.providers import load_providers


def response(verdict, confidence=0.8, summary="Checked the draft.", critical_risks=None, evidence_gaps=None):
    return json.dumps({"verdict": verdict, "confidence": confidence, "summary": summary,
                       "critical_risks": critical_risks or [], "evidence_gaps": evidence_gaps or []})


class ProviderConfigTests(unittest.TestCase):
    def test_ollama_fallback_is_one_reviewer(self):
        providers = load_providers(raw="", ollama_model="qwen2.5:7b", ollama_url="http://127.0.0.1:11434/api/chat")
        self.assertEqual(len(providers), 1)
        self.assertEqual(providers[0].trust_domain, "local")

    def test_duplicate_model_endpoint_cannot_count_twice(self):
        provider = {"id": "first", "protocol": "openai", "model": "qwen", "base_url": "http://127.0.0.1:1234/v1"}
        second = {**provider, "id": "second"}
        with self.assertRaisesRegex(ValueError, "duplicate"):
            load_providers(json.dumps([provider, second]))

    def test_remote_provider_requires_explicit_trust_domain(self):
        item = {"id": "cloud", "protocol": "openai", "model": "example", "base_url": "https://api.example.com/v1", "trust_domain": "remote"}
        provider = load_providers(json.dumps([item]))[0]
        self.assertEqual(provider.trust_domain, "remote")


class ConsensusTests(unittest.TestCase):
    def setUp(self):
        self.providers = load_providers(json.dumps([
            {"id": "review-a", "protocol": "openai", "model": "model-a", "base_url": "http://127.0.0.1:10001/v1"},
            {"id": "review-b", "protocol": "openai", "model": "model-b", "base_url": "http://127.0.0.1:10002/v1"},
            {"id": "review-c", "protocol": "openai", "model": "model-c", "base_url": "http://127.0.0.1:10003/v1"},
        ]))

    def test_independent_support_is_never_auto_approval(self):
        votes={"review-a":"support", "review-b":"support", "review-c":"revise"}
        report=conduct("Explain the change", "A draft", self.providers,
                       reviewer=lambda provider, system, prompt: response(votes[provider.id]))
        self.assertEqual(report["status"], "multi-provider-support")
        self.assertGreaterEqual(report["independent_review_count"], 2)
        self.assertFalse(report["auto_approve"])
        self.assertEqual(report["arbiter_decision"], "human-check-recommended")
        self.assertEqual(report["confidence_type"], "uncalibrated-model-agreement-proxy")

    def test_critical_risk_escalates_even_if_all_models_support(self):
        report=conduct("Review", "Draft", self.providers,
                       reviewer=lambda *_: response("support", critical_risks=["Missing authorization evidence"]))
        self.assertEqual(report["status"], "risk-escalated")
        self.assertFalse(report["auto_approve"])

    def test_invalid_response_abstains_and_cannot_create_consensus(self):
        def mock(provider, *_):
            return "not json" if provider.id != "review-c" else response("support")
        report=conduct("Review", "Draft", self.providers, reviewer=mock)
        self.assertEqual(report["status"], "insufficient-independent-reviews")
        self.assertEqual(report["independent_review_count"], 1)
        self.assertEqual(report["votes"][0]["verdict"], "abstain")

    def test_provider_self_reported_confidence_is_not_passed_through(self):
        vote=parse_vote(self.providers[0], response("support", confidence=1.0))
        report=aggregate([vote])
        self.assertLessEqual(report["confidence"], 0.5)
        self.assertEqual(report["status"], "insufficient-independent-reviews")


if __name__ == "__main__":
    unittest.main()
