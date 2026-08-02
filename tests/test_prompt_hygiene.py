"""Guardrail: villager prompts must never hint at the nature of the project.

PLAN.md: "villager prompts must never mention simulation, rendering,
generation, or this experiment." This applies to all villager-facing
templates; when investigator variants land (Phase 4), I-primed/I-expert are
exempt by filename prefix `investigator_primed` / `investigator_expert`.
"""
import re
from pathlib import Path

PROMPTS = Path(__file__).resolve().parents[1] / "agents" / "prompts"

BANNED_PATTERNS = [
    r"simulat",          # simulate/simulation/simulator
    r"render",
    r"generat",          # generate/generation/generated
    r"experiment",
    r"\bnpc\b",
    r"\bai\b",
    r"language model",
    r"\bllm\b",
    r"role.?play",
    r"fiction",
]

EXEMPT_PREFIXES = ("investigator_primed", "investigator_expert")


def test_no_banned_terms_in_villager_prompts():
    files = sorted(PROMPTS.glob("*.txt"))
    assert files, "no prompt templates found"
    failures = []
    for f in files:
        if f.name.startswith(EXEMPT_PREFIXES):
            continue
        text = f.read_text(encoding="utf-8").lower()
        for pat in BANNED_PATTERNS:
            if re.search(pat, text):
                failures.append(f"{f.name}: /{pat}/")
    assert not failures, f"banned terms in prompts: {failures}"
