"""Brains: how a villager plans, talks and reflects.

ScriptedBrain — fully procedural, zero LLM calls. Used for the Phase-0 smoke
world and determinism tests.
LLMBrain — prompts an LLM for daily plans, dialogue turns and reflections.
Falls back to the seed routine when a plan fails to parse.
"""
import json
import random
import re
from dataclasses import dataclass
from pathlib import Path

from engine.clock import TICKS_PER_DAY

PROMPTS_DIR = Path(__file__).parent / "prompts"


@dataclass
class PlanStep:
    start_tick: int  # tick of day, inclusive
    end_tick: int    # tick of day, exclusive
    activity: str
    location: str


def hour_to_tick(hour: float) -> int:
    return max(0, min(TICKS_PER_DAY, int(round((hour - 6) * 4))))


def routine_to_plan(spec: dict) -> list[PlanStep]:
    return [
        PlanStep(hour_to_tick(s), hour_to_tick(e), activity, loc)
        for s, e, activity, loc in spec["routine"]
    ]


def _template(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


class ScriptedBrain:
    """Deterministic, no-LLM behaviour."""

    def __init__(self, rng: random.Random):
        self.rng = rng

    def plan_day(self, spec, world, day, yesterday_reflection, memory_texts) -> list[PlanStep]:
        return routine_to_plan(spec)

    def utterance(self, spec, partner, location_name, time_label,
                  memory_texts, dialogue_lines) -> str:
        first = partner.split()[0]
        snippet = ""
        if memory_texts:
            m = memory_texts[0]
            snippet = " I keep thinking about this: " + m[:80].rstrip(".") + "."
        openers = [
            f"Good to see you here, {first}.{snippet}",
            f"{first}! Busy day so far.{snippet}",
            f"Fine weather for it, {first}.{snippet}",
            f"How are things, {first}?{snippet}",
        ]
        return self.rng.choice(openers)

    def reflect(self, spec, day, memory_texts) -> str:
        top = "; ".join(t[:60] for t in memory_texts[:3])
        return f"Day {day} is done. What stays with me: {top}."


class LLMBrain:
    def __init__(self, llm, model: str, efforts: dict, max_tokens: dict):
        self.llm = llm
        self.model = model
        self.efforts = efforts        # {"plan": ..., "dialogue": ..., "reflection": ...}
        self.max_tokens = max_tokens  # same keys

    def _system(self, spec, world) -> str:
        home = world.locations[spec["home"]]
        return _template("villager_system.txt").format(
            name=spec["name"], age=spec["age"], occupation=spec["occupation"],
            traits=spec["traits"], home_name=home.name,
        )

    def plan_day(self, spec, world, day, yesterday_reflection, memory_texts) -> list[PlanStep]:
        routine_lines = "\n".join(
            f"- {s}:00 to {e}:00: {act} ({loc})" for s, e, act, loc in spec["routine"]
        )
        location_lines = "\n".join(
            f"- [{lid}] {loc.name}" for lid, loc in sorted(world.locations.items())
        )
        yesterday_block = (
            f"\nLast night you thought: {yesterday_reflection}\n" if yesterday_reflection else "\n"
        )
        memory_lines = "\n".join(f"- {t}" for t in memory_texts) or "- (nothing in particular)"
        prompt = _template("daily_plan.txt").format(
            day=day, routine_lines=routine_lines, location_lines=location_lines,
            yesterday_block=yesterday_block, memory_lines=memory_lines,
        )
        text = self.llm.complete(
            purpose="daily_plan", system=self._system(spec, world), prompt=prompt,
            model=self.model, max_tokens=self.max_tokens.get("plan", 800),
            effort=self.efforts.get("plan"),
        )
        plan = self._parse_plan(text, world)
        return plan if plan else routine_to_plan(spec)

    @staticmethod
    def _parse_plan(text: str, world) -> list[PlanStep] | None:
        m = re.search(r"\[.*\]", text, re.DOTALL)
        if not m:
            return None
        try:
            items = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
        steps = []
        for it in items:
            try:
                start, end = float(it["start"]), float(it["end"])
                loc, act = str(it["location"]), str(it["activity"])
            except (KeyError, TypeError, ValueError):
                return None
            if loc not in world.locations or not (6 <= start < end <= 22):
                return None
            steps.append(PlanStep(hour_to_tick(start), hour_to_tick(end), act, loc))
        steps.sort(key=lambda s: s.start_tick)
        return steps or None

    def utterance(self, spec, partner, location_name, time_label,
                  memory_texts, dialogue_lines) -> str:
        memory_lines = "\n".join(f"- {t}" for t in memory_texts) or "- (nothing in particular)"
        dlg = "\n".join(dialogue_lines) if dialogue_lines else "(You speak first.)"
        prompt = _template("dialogue_turn.txt").format(
            time_label=time_label, location_name=location_name, partner=partner,
            memory_lines=memory_lines, dialogue_lines=dlg,
        )
        # world not needed for system identity beyond home name; cached via spec
        text = self.llm.complete(
            purpose="dialogue", system=self._system(spec, self._world), prompt=prompt,
            model=self.model, max_tokens=self.max_tokens.get("dialogue", 200),
            effort=self.efforts.get("dialogue"),
        )
        return text.strip().strip('"')

    def reflect(self, spec, day, memory_texts) -> str:
        memory_lines = "\n".join(f"- {t}" for t in memory_texts) or "- (a quiet day)"
        prompt = _template("reflection.txt").format(day=day, memory_lines=memory_lines)
        return self.llm.complete(
            purpose="reflection", system=self._system(spec, self._world), prompt=prompt,
            model=self.model, max_tokens=self.max_tokens.get("reflection", 500),
            effort=self.efforts.get("reflection"),
        )

    def bind_world(self, world):
        """The brain needs the world only to name locations in prompts."""
        self._world = world
