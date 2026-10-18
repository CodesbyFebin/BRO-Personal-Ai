"""Fail-closed action policy used by the current approval-only MVP."""
from .routing import classify

def action_policy(prompt: str, model_configured: bool = False) -> dict:
    decision=classify(prompt, model_configured)
    return {
        "decision": decision.to_dict(),
        "execution": "disabled",
        "approval": "required" if decision.requires_human_approval else "not-applicable",
        "policy_version": "BRO-LOCAL-POLICY-1",
    }
