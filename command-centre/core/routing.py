"""Typed local routing and Jev-compatible policy questions.

This is a transparent rule engine, not a Jev/Kev neural model. It returns
Choice (complexity), Score (0-1 confidence), and Noul (side-effect risk).
"""
from __future__ import annotations
from dataclasses import asdict, dataclass
import re

MUTATING = re.compile(r"\b(send|delete|deploy|publish|buy|sell|trade|transfer|execute|write|modify|shutdown|restart|merge|post|commit)\b", re.I)
SENSITIVE = re.compile(r"\b(password|secret|private key|wallet|medical|legal|financial|payment)\b", re.I)
HIGH_STAKES = re.compile(r"\b(production|security|financial|medical|legal|incident|breach|trade|wallet)\b", re.I)
COMPLEX = re.compile(r"\b(architecture|compare|analy[sz]e|investigate|debug|design|migrate|roadmap|root cause|multi.step)\b", re.I)

@dataclass(frozen=True)
class RouteDecision:
    choice: str
    score: float
    noul: str
    model_class: str
    requires_human_approval: bool
    reasons: tuple[str, ...]

    def to_dict(self) -> dict:
        return asdict(self)

def classify(prompt: str, model_configured: bool = False) -> RouteDecision:
    words = re.findall(r"\w+", prompt)
    risk_reasons=[]
    if MUTATING.search(prompt): risk_reasons.append("possible side effect verb")
    if SENSITIVE.search(prompt): risk_reasons.append("sensitive topic")
    if HIGH_STAKES.search(prompt): risk_reasons.append("high-stakes topic")
    if len(words) > 110 or COMPLEX.search(prompt):
        complexity="complex"
    elif len(words) > 35 or len(prompt) > 220:
        complexity="simple"
    else:
        complexity="trivial"
    score=min(.98, .66 + min(len(words), 100) / 400 + (.12 if HIGH_STAKES.search(prompt) else 0))
    noul="review" if risk_reasons else "low-risk"
    reasons=tuple(risk_reasons or ["no side-effect or sensitive terms matched local rules"])
    return RouteDecision(complexity, round(score, 2), noul,
                         "local-model" if model_configured else "demo-fallback",
                         bool(risk_reasons), reasons)
