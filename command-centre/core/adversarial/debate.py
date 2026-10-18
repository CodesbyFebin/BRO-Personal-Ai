"""Blind first-pass model review and conservative weighted aggregation.

The aggregate measures reviewer agreement only. It is not calibrated truth,
source verification, a safety certification, or permission to execute tools.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
import json
import re
from typing import Callable

from .providers import ModelProvider

SYSTEM = """You are an independent adversarial reviewer. Review the task and draft without tools or web access. First assess the task independently, then inspect the draft for unsupported claims, omissions, and risks. Do not infer that another model's confidence is evidence. Return one JSON object only with keys: verdict (support, revise, reject, or abstain), confidence (number 0 to 1, your subjective confidence only), summary (string), critical_risks (array of short strings), evidence_gaps (array of short strings). Never claim a source was checked unless it is included in the task."""


@dataclass(frozen=True)
class Vote:
    provider_id: str
    model: str
    trust_domain: str
    weight: float
    verdict: str
    confidence: float
    summary: str
    critical_risks: tuple[str, ...]
    evidence_gaps: tuple[str, ...]
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _strings(value: object, limit: int = 8) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(x).strip()[:240] for x in value[:limit] if str(x).strip())


def parse_vote(provider: ModelProvider, response: str) -> Vote:
    text = response.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("reviewer returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("reviewer result must be an object")
    verdict = payload.get("verdict")
    if verdict not in {"support", "revise", "reject", "abstain"}:
        raise ValueError("reviewer verdict is invalid")
    try:
        confidence = float(payload.get("confidence"))
    except (TypeError, ValueError) as exc:
        raise ValueError("reviewer confidence is invalid") from exc
    if not 0 <= confidence <= 1:
        raise ValueError("reviewer confidence must be between 0 and 1")
    summary = payload.get("summary", "")
    if not isinstance(summary, str):
        raise ValueError("reviewer summary must be text")
    return Vote(provider.id, provider.model, provider.trust_domain, provider.weight, verdict, confidence,
                summary[:1000], _strings(payload.get("critical_risks")), _strings(payload.get("evidence_gaps")))


def _failed_vote(provider: ModelProvider, error: str) -> Vote:
    return Vote(provider.id, provider.model, provider.trust_domain, provider.weight, "abstain", 0.0,
                "Reviewer unavailable or output could not be parsed.", (), (), error)


def aggregate(votes: list[Vote]) -> dict:
    eligible = [v for v in votes if v.verdict != "abstain" and v.error is None]
    total = sum(v.weight for v in eligible)
    weighted = {name: sum(v.weight for v in eligible if v.verdict == name) for name in ("support", "revise", "reject")}
    shares = {name: (weighted[name] / total if total else 0.0) for name in weighted}
    agreement = max(shares.values(), default=0.0)
    critical = tuple(dict.fromkeys(risk for vote in eligible for risk in vote.critical_risks))
    gaps = tuple(dict.fromkeys(gap for vote in eligible for gap in vote.evidence_gaps))
    if len(eligible) < 2:
        status = "insufficient-independent-reviews"
    elif critical:
        status = "risk-escalated"
    elif shares["reject"] >= 0.5:
        status = "reviewers-reject-draft"
    elif shares["support"] >= (2 / 3):
        status = "multi-provider-support"
    else:
        status = "reviewer-disagreement"
    # Subjective confidence is capped and discounted by weighted disagreement.
    mean_self_confidence = sum(v.weight * v.confidence for v in eligible) / total if total else 0.0
    confidence = round(min(0.5, agreement * mean_self_confidence * 0.5), 2)
    flags = []
    if len(eligible) < 2:
        flags.append("Fewer than two independent reviewers returned valid votes.")
    if critical:
        flags.extend(critical)
    if gaps:
        flags.extend(f"Evidence gap: {gap}" for gap in gaps)
    if not flags:
        flags.append("Model agreement does not verify factual claims.")
    return {"status": status, "agreement_score": round(agreement, 2), "confidence": confidence,
            "confidence_type": "uncalibrated-model-agreement-proxy", "vote_shares": {k: round(v, 2) for k, v in shares.items()},
            "independent_review_count": len(eligible), "critical_risks": list(critical),
            "evidence_gaps": list(gaps), "hallucination_flags": flags,
            "arbiter_decision": "human-check-recommended", "auto_approve": False,
            "evidence_status": "models-only-no-source-verification",
            "votes": [vote.to_dict() for vote in votes]}


def conduct(task: str, draft: str, providers: tuple[ModelProvider, ...],
            reviewer: Callable[[ModelProvider, str, str], str] | None = None) -> dict:
    if not providers:
        return {"status": "no-independent-reviewers", "agreement_score": 0.0, "confidence": 0.0,
                "confidence_type": "uncalibrated-model-agreement-proxy", "vote_shares": {},
                "independent_review_count": 0, "critical_risks": [], "evidence_gaps": ["No reviewer provider is configured."],
                "hallucination_flags": ["No independent verification was performed."],
                "arbiter_decision": "human-check-recommended", "auto_approve": False,
                "evidence_status": "no-independent-review", "votes": []}
    def run(provider: ModelProvider) -> Vote:
        try:
            prompt = f"TASK:\n{task[:6000]}\n\nDRAFT TO REVIEW:\n{draft[:8000]}"
            response = reviewer(provider, SYSTEM, prompt) if reviewer else provider.complete(SYSTEM, prompt)
            return parse_vote(provider, response)
        except Exception as exc:
            return _failed_vote(provider, type(exc).__name__)
    votes=[]
    with ThreadPoolExecutor(max_workers=min(5, len(providers))) as pool:
        futures=[pool.submit(run, provider) for provider in providers]
        for future in as_completed(futures):
            votes.append(future.result())
    # Keep report order stable even though provider requests ran concurrently.
    by_id={vote.provider_id: vote for vote in votes}
    ordered=[by_id[p.id] for p in providers]
    return aggregate(ordered)
