"""Compatibility facade for the multi-provider adversarial review engine."""
from dataclasses import dataclass, asdict
from core.adversarial.debate import conduct
from core.adversarial.providers import ModelProvider

@dataclass(frozen=True)
class DebateReport:
    advocate_summary: str
    challenger_summary: str
    arbiter_decision: str
    confidence: float
    hallucination_flags: tuple[str, ...]
    evidence_status: str
    details: dict

    def to_dict(self) -> dict:
        return asdict(self)

def review(draft: str, verifier_text: str | None = None, model_used: bool = False,
           task: str = "", providers: tuple[ModelProvider, ...] = ()) -> DebateReport:
    details = conduct(task, draft, providers) if providers else conduct(task, draft, ())
    summary = "No configured reviewers; claims remain unverified."
    if verifier_text:
        summary = verifier_text[:800]
    elif details.get("votes"):
        summaries = [f"{vote['provider_id']} ({vote['verdict']}): {vote['summary']}" for vote in details["votes"] if vote["error"] is None]
        summary = "\n".join(summaries)[:2000] or "All configured reviewers abstained or failed."
    flags = list(details["hallucination_flags"])
    if model_used and not providers:
        flags.append("The draft came from one model; there is no independent reviewer configured.")
    return DebateReport(
        advocate_summary="Draft produced by the configured local model." if model_used else "Draft produced by local demo fallback.",
        challenger_summary=summary,
        arbiter_decision=details["arbiter_decision"],
        confidence=details["confidence"],
        hallucination_flags=tuple(dict.fromkeys(flags)),
        evidence_status=details["evidence_status"],
        details=details,
    )
