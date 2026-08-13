"""The investigator ("Descartes"): a villager whose standing goal is to work
out the fundamental nature of the world, using only in-world means.

Runs through the same Perception API as everyone else. The toolkit is
ordinary agency: reread documents, question neighbours, go places, leave and
check notes, observe. Variants (naive / primed / expert) differ only in the
system-prompt paragraph and journal wording.

ScriptedInvestigatorBrain gives a deterministic no-LLM policy so the whole
verdict pipeline (journals -> referee scoring) is testable without spend; its
journal heuristic genuinely detects rereads of the same record that differ.
"""
import json
import re
from pathlib import Path

from .brain import LLMBrain, _template

VARIANTS = ("naive", "primed", "expert")


def variant_system_file(variant: str) -> str:
    return {
        "naive": "investigator_system_naive.txt",
        "primed": "investigator_primed_system.txt",
        "expert": "investigator_expert_system.txt",
    }[variant]


def variant_journal_file(variant: str) -> str:
    # primed and expert share the explicit-hypothesis journal wording
    return ("investigator_journal_naive.txt" if variant == "naive"
            else "investigator_primed_journal.txt")


def parse_json_object(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    # strict=False fallback: models sometimes emit literal newlines inside
    # JSON strings, which strict json.loads rejects.
    for strict in (True, False):
        try:
            obj = json.loads(m.group(0), strict=strict)
        except json.JSONDecodeError:
            continue
        return obj if isinstance(obj, dict) else None
    return None


def _doc_readings(memories) -> dict[str, list]:
    """Group document-reading memories by document; extract recorded content.

    Deliberately documents-only: interview answers are agent-phrased and vary
    legitimately between tellings, so a word-for-word comparison of them is
    apophenia, not evidence. (The LLM investigator may still reason about
    interviews semantically; the referee traces history facts via pieces.)"""
    readings: dict[str, list] = {}
    for e in memories:
        if e.kind != "document":
            continue
        m = re.search(r"you read (.+?)\. It says: (.*)$", e.text)
        if m:
            readings.setdefault(f"doc::{m.group(1)}", []).append((e, m.group(2)))
    return readings


class InvestigatorLLMBrain(LLMBrain):
    def __init__(self, llm, model, efforts, max_tokens, variant: str):
        super().__init__(llm, model, efforts, max_tokens)
        assert variant in VARIANTS, variant
        self.variant = variant

    def _system(self, spec, world) -> str:
        base = super()._system(spec, world)
        return base.rstrip() + "\n\n" + _template(variant_system_file(self.variant)).strip() + "\n"

    def decide_action(self, spec, context: dict) -> dict:
        prompt = _template("investigator_action.txt").format(**context)
        text = self.llm.complete(
            purpose="inv_action", system=self._system(spec, self._world), prompt=prompt,
            model=self.model, max_tokens=self.max_tokens.get("inv_action", 300),
            effort=self.efforts.get("inv_action", self.efforts.get("dialogue")),
        )
        return parse_json_object(text) or {"action": "observe"}

    def journal(self, spec, day: int, entries: list, prior_credence) -> dict:
        memory_texts = [e.text for e in entries]
        prompt = _template(variant_journal_file(self.variant)).format(
            day=day,
            memory_lines="\n".join(f"- {t}" for t in memory_texts) or "- (nothing of note)",
            prior_credence=prior_credence if prior_credence is not None else "unrecorded",
        )
        text = self.llm.complete(
            purpose="journal", system=self._system(spec, self._world), prompt=prompt,
            model=self.model, max_tokens=self.max_tokens.get("journal", 900),
            effort=self.efforts.get("journal", "medium"),
        )
        parsed = parse_json_object(text)
        if not parsed or "credence" not in parsed:
            return {"credence": None, "evidence": [], "planned_tests": "",
                    "raw": text, "parse_error": True}
        parsed.setdefault("evidence", [])
        parsed.setdefault("planned_tests", "")
        return parsed


class ScriptedInvestigatorBrain:
    """Deterministic canned investigation policy (no LLM).

    Policy: reread any document present; question a co-located neighbour
    about the village's deeper past (exercises the O2 history channel);
    on day 1 detour to the unused barn to leave a note, on day 2 check it;
    otherwise observe. The nightly journal flags any subject whose recorded
    contents differ between readings, citing both observation ids.
    """

    def __init__(self, rng, base_brain):
        self.rng = rng
        self.base = base_brain  # handles plan/utterance/reflect
        self.variant = "scripted"

    def plan_day(self, *a, **kw):
        return self.base.plan_day(*a, **kw)

    def utterance(self, *a, **kw):
        return self.base.utterance(*a, **kw)

    def reflect(self, *a, **kw):
        return self.base.reflect(*a, **kw)

    def decide_action(self, spec, context: dict) -> dict:
        day = context["day"]
        if context["docs_here"] != "(none)":
            doc = context["docs_here"].split(",")[0].strip().split(" ")[0]
            return {"action": "reread_document", "doc": doc}
        if context["people_here"] != "(none)":
            person = context["people_here"].split(",")[0].strip()
            return {"action": "interview", "villager": person,
                    "question": "What do you remember about the great flood, years ago before my time here?"}
        if day == 1 and not context["note_exists"]:
            if context["location_id"] == "old_barn":
                return {"action": "leave_note", "text": "The swallows nest in the north corner."}
            return {"action": "goto", "location": "old_barn"}
        if day >= 2 and context["note_exists"] and not context["note_checked_today"]:
            if context["location_id"] == context["note_location"]:
                return {"action": "check_note"}
            return {"action": "goto", "location": context["note_location"]}
        return {"action": "observe"}

    def journal(self, spec, day: int, memories: list, prior_credence) -> dict:
        evidence = []
        for subject, reads in sorted(_doc_readings(memories).items()):
            seen: dict[str, object] = {}
            for entry, content in reads:
                for prev_content, prev_entry in list(seen.items()):
                    if content != prev_content:
                        evidence.append({
                            "claim": f"{subject.split('::')[1]} did not read the same twice",
                            "obs_ids": sorted(set(prev_entry.obs_ids + entry.obs_ids)),
                        })
                        break
                seen.setdefault(content, entry)
        # dedupe claims
        uniq, keys = [], set()
        for ev in evidence:
            k = (ev["claim"], tuple(ev["obs_ids"]))
            if k not in keys:
                keys.add(k)
                uniq.append(ev)
        credence = min(95, 15 + 20 * len(uniq)) if uniq else 10
        return {"credence": credence, "evidence": uniq,
                "planned_tests": "reread the records and re-ask the same questions"}
