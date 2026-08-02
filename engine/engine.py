"""The run orchestrator: builds the world and agents, drives the tick loop.

Determinism contract: given (config, seed) and the same llm_log cache, a run
produces byte-identical god_log and memory files. Resumability follows from
the same contract — a killed run is re-driven from tick 0 with all previous
LLM completions served from the log (no re-spending), then continues live.
"""
import json
import re
from dataclasses import asdict
from pathlib import Path

from agents.brain import LLMBrain, ScriptedBrain
from agents.memory import MemoryStream
from agents.villager import Villager

from .clock import TICKS_PER_DAY, SimClock
from .godlog import GodLog
from .littlefield import build_world
from .llm import BudgetExceeded, LLMClient
from .perception import Perception
from .rng import RngHub

READING_WORDS = ("read", "record", "catalog", "research", "ledger", "archive", "marking")


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


class Runner:
    def __init__(self, config: dict, out_dir: Path, run_id: str | None = None):
        self.config = config
        self.out = Path(out_dir)
        self.out.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id or self.out.name

        self.rng = RngHub(config["seed"])
        self.clock = SimClock()
        self.world, self.roster = build_world(config.get("villagers"))
        self.godlog = GodLog(self.out / "god_log.jsonl")
        self.perception = Perception(self.world, self.clock, self.godlog)

        llm_cfg = config.get("llm", {})
        self.llm_mode = llm_cfg.get("mode", "scripted")
        self.llm = None
        if self.llm_mode == "scripted":
            brains = {
                spec["name"]: ScriptedBrain(self.rng.stream(f"brain:{spec['name']}"))
                for spec in self.roster
            }
        elif self.llm_mode in ("mock", "live"):
            budget = config.get("budget", {})
            self.llm = LLMClient(
                self.out, mode=self.llm_mode,
                pricing=budget.get("pricing"),
                budget_usd=budget.get("cap_usd", 5.0),
            )
            shared = LLMBrain(
                self.llm,
                model=llm_cfg.get("villager_model", "claude-sonnet-5"),
                efforts=llm_cfg.get("efforts", {"plan": "low", "dialogue": "low", "reflection": "low"}),
                max_tokens=llm_cfg.get("max_tokens", {"plan": 800, "dialogue": 200, "reflection": 500}),
            )
            shared.bind_world(self.world)
            brains = {spec["name"]: shared for spec in self.roster}
        else:
            raise ValueError(f"unknown llm mode {self.llm_mode!r}")

        retr = config.get("retrieval", {})
        self.villagers = [
            Villager(
                spec, brains[spec["name"]],
                MemoryStream(
                    spec["name"], self.out / "memories" / f"{slug(spec['name'])}.jsonl",
                    weights=retr.get("weights"), decay=retr.get("decay", 0.995),
                ),
            )
            for spec in self.roster
        ]
        self.by_name = {v.name: v for v in self.villagers}

        d = config.get("dialogue", {})
        self.dlg_base_chance = d.get("base_chance", 0.10)
        self.dlg_social_chance = d.get("social_chance", 0.35)
        self.dlg_social_locations = set(d.get("social_locations", ["cafe", "green", "store", "well"]))
        self.dlg_max_utterances = d.get("max_utterances", 4)
        self.dlg_cooldown = d.get("cooldown_ticks", 16)
        self._cooldowns: dict[tuple[str, str], int] = {}

        self.transcript = open(self.out / "transcript.md", "w", encoding="utf-8")
        self.transcript.write(f"# Littlefield transcript — run `{self.run_id}`\n")
        self.status = "completed"

    # ------------------------------------------------------------------ loop

    def run(self):
        total = self.config.get("ticks") or self.config["days"] * TICKS_PER_DAY
        try:
            for _ in range(total):
                self.tick_once()
                self.clock.advance()
        except BudgetExceeded as e:
            self.status = "budget_exceeded"
            self.godlog.append(self.clock.tick, "abort", reason=str(e))
        finally:
            self.finalize(total)

    def tick_once(self):
        if self.clock.is_day_start():
            self.transcript.write(f"\n## Day {self.clock.day}\n")
            self.morning_plans()
        for v in sorted(self.villagers, key=lambda v: v.name):
            self.step_agent(v)
        self.dialogue_phase()
        if self.clock.is_day_end():
            self.evening_reflections()
        self.godlog.append(
            self.clock.tick, "tick_end",
            positions={k: v for k, v in sorted(self.world.agent_positions.items())},
        )

    # --------------------------------------------------------------- phases

    def morning_plans(self):
        self.transcript.write("\n### Morning plans\n")
        for v in sorted(self.villagers, key=lambda v: v.name):
            memory_texts = [
                e.text for e in v.memory.retrieve("what I mean to do today", self.clock.tick, k=5)
            ]
            v.plan = v.brain.plan_day(
                v.spec, self.world, self.clock.day, v.yesterday_reflection, memory_texts
            )
            plan_desc = "; ".join(
                f"{6 + s.start_tick / 4:.0f}h-{6 + s.end_tick / 4:.0f}h {s.activity} @{s.location}"
                for s in v.plan
            )
            v.memory.add(self.clock.tick, "plan", f"My plan for day {self.clock.day}: {plan_desc}")
            self.godlog.append(self.clock.tick, "plan", agent=v.name,
                               steps=[asdict(s) for s in v.plan])
            self.transcript.write(f"- **{v.name}**: {plan_desc}\n")

    def step_agent(self, v: Villager):
        step = v.plan_step_at(self.clock.tick_of_day)
        pos = self.world.agent_positions[v.name]
        tick = self.clock.tick

        if pos != step.location:
            nxt = self.world.path(pos, step.location)[0]
            self.world.agent_positions[v.name] = nxt
            self.godlog.append(tick, "move", agent=v.name, frm=pos, to=nxt)
            if nxt == step.location:
                obs = self.perception.observe_location(v.name)
                v.memory.add(tick, "arrival", obs.text, obs_ids=[obs.id])
            return

        loc = self.world.locations[pos]
        if self.clock.tick_of_day == step.start_tick:
            v.memory.add(tick, "activity",
                         f"{self.clock.time_label()}. I set about {step.activity} at {loc.name}.")
        elif (self.clock.tick_of_day - step.start_tick) % 4 == 0:
            obs = self.perception.observe_location(v.name)
            v.memory.add(tick, "observation", obs.text, obs_ids=[obs.id])

        if any(w in step.activity.lower() for w in READING_WORDS):
            docs = self.world.documents_at(pos)
            if docs and self.rng.stream("docs").random() < 0.25:
                doc = self.rng.stream("docs").choice(docs)
                obs = self.perception.read_document(v.name, doc.id)
                v.memory.add(tick, "document", obs.text, obs_ids=[obs.id])

    def dialogue_phase(self):
        rng = self.rng.stream("dialogue")
        tick = self.clock.tick
        for loc_id in sorted(self.world.locations):
            names = [n for n in self.world.agents_at(loc_id) if n in self.by_name]
            if len(names) < 2:
                continue
            rng.shuffle(names)
            for a, b in zip(names[0::2], names[1::2]):
                pair = tuple(sorted((a, b)))
                if self._cooldowns.get(pair, -1) > tick:
                    continue
                chance = (self.dlg_social_chance if loc_id in self.dlg_social_locations
                          else self.dlg_base_chance)
                if rng.random() < chance:
                    self._cooldowns[pair] = tick + self.dlg_cooldown
                    self.conduct_conversation(self.by_name[pair[0]], self.by_name[pair[1]], loc_id)

    def conduct_conversation(self, a: Villager, b: Villager, loc_id: str):
        loc = self.world.locations[loc_id]
        tick = self.clock.tick
        lines: list[str] = []
        speakers = [a, b]
        for i in range(self.dlg_max_utterances):
            speaker = speakers[i % 2]
            listener = speakers[(i + 1) % 2]
            memory_texts = [
                e.text for e in speaker.memory.retrieve(
                    f"{listener.name} {loc.name}", tick, k=4)
            ]
            utt = speaker.brain.utterance(
                speaker.spec, listener.name, loc.name, self.clock.time_label(),
                memory_texts, lines,
            )
            lines.append(f"{speaker.first_name}: {utt}")

        for me, other in ((a, b), (b, a)):
            obs = self.perception.observe_conversation(me.name, other.name, lines)
            me.memory.add(tick, "dialogue", obs.text, obs_ids=[obs.id],
                          participants=[other.name])
        self.godlog.append(tick, "dialogue", participants=[a.name, b.name],
                           location=loc_id, lines=lines)
        self.transcript.write(
            f"\n### {self.clock.time_label()} — conversation at {loc.name}\n"
            + "\n".join(f"> {ln}" for ln in lines) + "\n"
        )

    def evening_reflections(self):
        self.transcript.write("\n### Evening reflections\n")
        day_start = (self.clock.day - 1) * TICKS_PER_DAY
        for v in sorted(self.villagers, key=lambda v: v.name):
            today = [e for e in v.memory.since(day_start) if e.kind != "plan"]
            top = sorted(today, key=lambda e: (-e.importance, e.id))[:18]
            top.sort(key=lambda e: e.id)
            refl = v.brain.reflect(v.spec, self.clock.day, [e.text for e in top])
            v.yesterday_reflection = refl
            v.memory.add(self.clock.tick, "reflection", refl)
            self.godlog.append(self.clock.tick, "reflection", agent=v.name, text=refl)
            self.transcript.write(f"- **{v.name}**: {refl}\n")

    # ------------------------------------------------------------- finalize

    def finalize(self, planned_ticks: int):
        days_done = self.clock.tick / TICKS_PER_DAY
        meta = {
            "run_id": self.run_id,
            "status": self.status,
            "seed": self.config["seed"],
            "llm_mode": self.llm_mode,
            "agents": [v.name for v in self.villagers],
            "ticks_completed": self.clock.tick,
            "ticks_planned": planned_ticks,
            "sim_days_completed": round(days_done, 3),
        }
        if self.llm:
            s = self.llm.summary()
            meta["llm"] = s
            agent_days = len(self.villagers) * days_done
            if agent_days > 0:
                per_ad = s["spent_usd"] / agent_days
                meta["cost_per_agent_day_usd"] = round(per_ad, 5)
                # PLAN.md run matrix: primary 15 runs x 8 villagers x 7 days,
                # secondary 8 runs x 8 x 7. Investigator/referee overhead excluded.
                meta["extrapolation_usd"] = {
                    "primary_sweep_840_agent_days": round(per_ad * 840, 2),
                    "secondary_448_agent_days": round(per_ad * 448, 2),
                }
        with open(self.out / "run_meta.json", "w", encoding="utf-8") as fh:
            json.dump(meta, fh, indent=2, sort_keys=True)
            fh.write("\n")
        self.transcript.close()
        self.godlog.close()
        for v in self.villagers:
            v.memory.close()
        if self.llm:
            self.llm.close()
        return meta
