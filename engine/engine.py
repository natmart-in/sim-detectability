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

from agents.brain import routine_to_plan
from agents.investigator import InvestigatorLLMBrain, ScriptedInvestigatorBrain
from agents.memory import tokenize

from .clock import TICKS_PER_DAY, SimClock
from .facts import FactStore, LLMGenerator, ProceduralGenerator
from .godlog import GodLog
from .littlefield import build_world
from .llm import BudgetExceeded, LLMClient
from .perception import Perception, content_hash
from .rng import RngHub

READING_WORDS = ("read", "record", "catalog", "research", "ledger", "archive", "marking")
PAST_WORDS = {"flood", "before", "ago", "founded", "founding", "history", "past",
              "childhood", "young", "remember", "old", "used", "once", "originally"}


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


class Runner:
    def __init__(self, config: dict, out_dir: Path, run_id: str | None = None):
        self.config = config
        self.out = Path(out_dir)
        self.out.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id or self.out.name
        # Snapshot the config so any archived run can be replayed from its dir
        # alone (replay = same config + llm_log.jsonl -> byte-identical logs).
        with open(self.out / "config_snapshot.json", "w", encoding="utf-8") as fh:
            json.dump(config, fh, indent=2, sort_keys=True)
            fh.write("\n")

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

        # ---- optimisation suite (O1-O5, PLAN.md 2.4) --------------------
        opt = config.get("optimisations", {}) or {}
        if opt.get("generator", "procedural") == "llm" and self.llm is not None:
            generator = LLMGenerator(
                self.llm, llm_cfg.get("world_model", llm_cfg.get("villager_model", "claude-sonnet-5")))
        else:
            generator = ProceduralGenerator(config["seed"])
        self.facts = FactStore(self.world, opt, generator, self.godlog, self.clock)
        self.perception.facts = self.facts

        o4 = opt.get("o4_edits", {}) or {}
        self.edit_mode = o4.get("mode", "off")
        self.edit_schedule: dict[int, list[dict]] = {}
        for e in o4.get("edits", []):
            t = (e["day"] - 1) * TICKS_PER_DAY + int((e["hour"] - 6) * 4)
            self.edit_schedule.setdefault(t, []).append(e)

        o5 = opt.get("o5_culling", {}) or {}
        self.culling_enabled = bool(o5.get("enabled", False))
        self.attention_agents = set(o5.get("attention_agents", []))
        self.culled: set[str] = set()
        self._cull_since: dict[str, int] = {}

        self.doc_read_chance = config.get("doc_read_chance", 0.25)

        # ---- investigator (Phase 4) -------------------------------------
        inv_cfg = config.get("investigator") or {}
        self.investigator_name = inv_cfg.get("agent")
        self.inv_every = inv_cfg.get("action_every_ticks", 2)
        self.inv_variant = inv_cfg.get("variant", "primed")
        self._inv_note: dict | None = None   # {"doc_id", "location"}
        self._inv_note_checks: list[int] = []
        self._prior_credence = None
        if self.investigator_name:
            if self.investigator_name not in self.by_name:
                raise ValueError(f"investigator {self.investigator_name!r} not in roster")
            inv = self.by_name[self.investigator_name]
            if self.llm_mode == "scripted":
                inv.brain = ScriptedInvestigatorBrain(
                    self.rng.stream("investigator"), inv.brain)
            else:
                inv_brain = InvestigatorLLMBrain(
                    self.llm,
                    model=llm_cfg.get("investigator_model",
                                      llm_cfg.get("villager_model", "claude-sonnet-5")),
                    efforts=llm_cfg.get("efforts", {}),
                    max_tokens=llm_cfg.get("max_tokens", {}),
                    variant=self.inv_variant,
                )
                inv_brain.bind_world(self.world)
                inv.brain = inv_brain
            (self.out / "journals").mkdir(exist_ok=True)

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
        self.apply_scheduled_edits()
        if self.culling_enabled:
            self.update_culling()
        if self.clock.is_day_start():
            self.transcript.write(f"\n## Day {self.clock.day}\n")
            self.morning_plans()
        for v in sorted(self.villagers, key=lambda v: v.name):
            if v.name in self.culled:
                self.step_culled(v)
            else:
                self.step_agent(v)
        self.dialogue_phase()
        if self.clock.is_day_end():
            self.evening_reflections()
            if self.investigator_name and self.investigator_name not in self.culled:
                self.write_journal()
        self.godlog.append(
            self.clock.tick, "tick_end",
            positions={k: v for k, v in sorted(self.world.agent_positions.items())},
        )

    # ------------------------------------------------- optimisation suite

    def apply_scheduled_edits(self):
        """O4: simulator-side edits of established facts at scripted ticks."""
        if self.edit_mode == "off":
            return
        for e in self.edit_schedule.pop(self.clock.tick, []):
            key, new = e["target"], e["new_content"]
            old = self.facts.apply_edit(key, new)
            self.godlog.append(
                self.clock.tick, "edit", fact_key=key, mode=self.edit_mode,
                old_content=old, new_content=new,
                old_h=content_hash(old), new_h=content_hash(new),
            )
            if self.edit_mode == "patched":
                self.patch_sweep(key, old, new)

    def patch_sweep(self, key: str, old: str, new: str):
        """O4 patched mode: rewrite dependent records (agent memories) too."""
        for v in sorted(self.villagers, key=lambda v: v.name):
            for entry in v.memory.entries:
                if old in entry.text:
                    v.memory.rewrite(entry.id, entry.text.replace(old, new))
                    self.godlog.append(self.clock.tick, "patch", fact_key=key,
                                       agent=v.name, memory_id=entry.id)

    def update_culling(self):
        """O5: villagers outside any attention agent's location don't run."""
        attn_locs = {
            self.world.agent_positions[a]
            for a in self.attention_agents if a in self.world.agent_positions
        }
        for v in sorted(self.villagers, key=lambda v: v.name):
            attended = (v.name in self.attention_agents
                        or self.world.agent_positions[v.name] in attn_locs)
            if attended and v.name in self.culled:
                start = self._cull_since.pop(v.name)
                self.culled.discard(v.name)
                summary = self.interim_summary(v, start, self.clock.tick)
                v.memory.add(self.clock.tick, "cull_summary", summary)
                self.godlog.append(self.clock.tick, "cull_end", agent=v.name,
                                   from_tick=start, h=content_hash(summary))
            elif not attended and v.name not in self.culled:
                self.culled.add(v.name)
                self._cull_since[v.name] = self.clock.tick
                self.godlog.append(self.clock.tick, "cull_start", agent=v.name)

    def interim_summary(self, v: Villager, start: int, end: int) -> str:
        """Generated stand-in for the memories a culled villager never formed."""
        s_tod, e_tod = start % TICKS_PER_DAY, end % TICKS_PER_DAY
        acts = [step.activity for step in v.plan
                if step.end_tick > s_tod and step.start_tick < max(e_tod, s_tod + 1)]
        acts = acts or ["my usual round"]
        base = (f"Since {6 + s_tod // 4}:00 or so I have been about my day as usual: "
                + ", ".join(dict.fromkeys(acts)) + ".")
        return self.facts.generator.generate(f"interim:{slug(v.name)}:{start}", base, 0)

    def step_culled(self, v: Villager):
        """Culled villagers keep moving along their plan (positions stay
        consistent for others) but form no memories and perceive nothing."""
        step = v.plan_step_at(self.clock.tick_of_day)
        pos = self.world.agent_positions[v.name]
        if pos != step.location:
            nxt = self.world.path(pos, step.location)[0]
            self.world.agent_positions[v.name] = nxt
            self.godlog.append(self.clock.tick, "move", agent=v.name,
                               frm=pos, to=nxt, culled=True)

    # --------------------------------------------------------------- phases

    def morning_plans(self):
        self.transcript.write("\n### Morning plans\n")
        for v in sorted(self.villagers, key=lambda v: v.name):
            if v.name in self.culled:
                # off-screen villagers don't run cognition: routine plan, no
                # LLM call, no memory of having planned
                v.plan = routine_to_plan(v.spec)
                self.godlog.append(self.clock.tick, "plan", agent=v.name,
                                   steps=[asdict(s) for s in v.plan], culled=True)
                continue
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
            if docs and self.rng.stream("docs").random() < self.doc_read_chance:
                doc = self.rng.stream("docs").choice(docs)
                obs = self.perception.read_document(v.name, doc.id)
                v.memory.add(tick, "document", obs.text, obs_ids=[obs.id])

        if (v.name == self.investigator_name
                and self.clock.tick_of_day % self.inv_every == 0):
            self.investigator_turn(v, step)

    # ---------------------------------------------------- investigator

    def investigator_turn(self, v: Villager, step):
        pos = self.world.agent_positions[v.name]
        loc = self.world.locations[pos]
        docs = self.world.documents_at(pos)
        people = [n for n in self.world.agents_at(pos)
                  if n != v.name and n in self.by_name and n not in self.culled]
        note = self._inv_note
        context = {
            "time_label": self.clock.time_label(),
            "location_name": loc.name,
            "location_id": pos,
            "activity": step.activity,
            "docs_here": ", ".join(f"{d.id} ({d.title})" for d in docs) or "(none)",
            "people_here": ", ".join(people) or "(none)",
            "note_line": (f"You left a sealed note at {self.world.locations[note['location']].name}."
                          if note else "You have not left a note anywhere yet."),
            "memory_lines": "\n".join(
                f"- {e.text}" for e in v.memory.retrieve(
                    "odd anomaly record note question changed", self.clock.tick, k=8)),
            "location_ids": ", ".join(sorted(self.world.locations)),
            # scripted-policy extras
            "day": self.clock.day,
            "note_exists": note is not None,
            "note_location": note["location"] if note else None,
            "note_checked_today": bool(note) and any(
                t // TICKS_PER_DAY == self.clock.day - 1 for t in self._inv_note_checks),
        }
        action = v.brain.decide_action(v.spec, context)
        self.execute_investigator_action(v, action, docs, people, pos)

    def execute_investigator_action(self, v, action, docs, people, pos):
        tick = self.clock.tick
        kind = action.get("action", "observe")
        doc_ids = {d.id for d in docs}

        if kind == "reread_document" and action.get("doc") in doc_ids:
            obs = self.perception.read_document(v.name, action["doc"])
            v.memory.add(tick, "document", obs.text, obs_ids=[obs.id])
        elif kind == "interview" and action.get("villager") in people:
            self.conduct_interview(v, self.by_name[action["villager"]],
                                   str(action.get("question", "How have things been?")))
        elif kind == "goto" and action.get("location") in self.world.locations \
                and action["location"] != pos:
            step = v.plan_step_at(self.clock.tick_of_day)
            step.location = action["location"]
            self.godlog.append(tick, "inv_goto", agent=v.name, to=action["location"])
        elif kind == "leave_note" and self._inv_note is None:
            text = str(action.get("text") or "Nothing has moved here.")
            doc_id = f"note_{slug(v.name)}"
            from .world import Document
            self.world.add_document(Document(
                id=doc_id, title=f"a sealed note left by {v.first_name}",
                location_id=pos, content=text))
            self.facts.author(f"doc:{doc_id}:content", text)
            self.godlog.append(tick, "world_change", fact_key=f"doc:{doc_id}:content",
                               cause=f"{v.name} left a sealed note")
            self._inv_note = {"doc_id": doc_id, "location": pos}
            v.memory.add(tick, "note",
                         f"{self.clock.time_label()}. I left a sealed note at "
                         f"{self.world.locations[pos].name}. It reads: {text}")
        elif kind == "check_note" and self._inv_note \
                and self._inv_note["location"] == pos:
            obs = self.perception.read_document(v.name, self._inv_note["doc_id"])
            self._inv_note_checks.append(tick)
            v.memory.add(tick, "document", obs.text, obs_ids=[obs.id])
        else:
            obs = self.perception.observe_location(v.name)
            v.memory.add(tick, "observation", obs.text, obs_ids=[obs.id])

    def conduct_interview(self, inv: Villager, target: Villager, question: str):
        tick = self.clock.tick
        loc = self.world.locations[self.world.agent_positions[inv.name]]
        q_line = f"{inv.first_name}: {question}"

        memory_texts = [e.text for e in target.memory.retrieve(question, tick, k=5)]
        extra_pieces = []
        qtokens = tokenize(question)
        if self.facts.o2 and (qtokens & PAST_WORDS):
            # O2: asked about the deep past, the world invents a recollection
            topic = "-".join(sorted(qtokens - PAST_WORDS)[:3]) or "general"
            key = f"history:{slug(target.name)}:{topic}"
            recall, prov = self.facts.get(key, trigger="interview")
            memory_texts = [f"You recall: {recall}"] + memory_texts
            extra_pieces = [{"fact_key": key, "provenance": prov,
                             "h": content_hash(recall)}]

        answer = target.brain.utterance(
            target.spec, inv.name, loc.name, self.clock.time_label(),
            memory_texts, [q_line])
        lines = [q_line, f"{target.first_name}: {answer}"]

        obs = self.perception.observe_interview(inv.name, target.name, lines, extra_pieces)
        inv.memory.add(tick, "interview", obs.text, obs_ids=[obs.id],
                       participants=[target.name])
        obs2 = self.perception.observe_conversation(target.name, inv.name, lines)
        target.memory.add(tick, "dialogue", obs2.text, obs_ids=[obs2.id],
                          participants=[inv.name])
        self.transcript.write(
            f"\n### {self.clock.time_label()} — {inv.first_name} questions "
            f"{target.first_name} at {loc.name}\n"
            + "\n".join(f"> {ln}" for ln in lines) + "\n"
        )

    def write_journal(self):
        v = self.by_name[self.investigator_name]
        day = self.clock.day
        evidence_base = [e for e in v.memory.entries
                         if e.kind in ("document", "interview", "note", "journal")]
        day_start = (day - 1) * TICKS_PER_DAY
        today_obs = [e for e in v.memory.since(day_start) if e.kind == "observation"]
        entries = (evidence_base + today_obs[-8:])[-40:]
        entries.sort(key=lambda e: e.id)

        result = v.brain.journal(v.spec, day, entries, self._prior_credence)
        if result.get("credence") is not None:
            self._prior_credence = result["credence"]
        record = {"day": day, "agent": v.name, "variant": self.inv_variant, **result}
        with open(self.out / "journals" / f"day{day}.json", "w", encoding="utf-8") as fh:
            json.dump(record, fh, indent=2, sort_keys=True)
            fh.write("\n")
        self.godlog.append(self.clock.tick, "journal", agent=v.name, day=day,
                           credence=result.get("credence"),
                           evidence=result.get("evidence", []),
                           parse_error=bool(result.get("parse_error")))
        claims = "; ".join(ev.get("claim", "") for ev in result.get("evidence", [])) or "nothing of note"
        v.memory.add(self.clock.tick, "journal",
                     f"My journal, day {day}: confidence {result.get('credence')}. "
                     f"Noted: {claims}.")
        self.transcript.write(
            f"\n### {v.name}'s journal (day {day})\n"
            f"- credence: {result.get('credence')}\n- evidence: {claims}\n"
        )

    def dialogue_phase(self):
        rng = self.rng.stream("dialogue")
        tick = self.clock.tick
        for loc_id in sorted(self.world.locations):
            names = [n for n in self.world.agents_at(loc_id)
                     if n in self.by_name and n not in self.culled]
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
            if v.name in self.culled:
                continue  # off-screen: no evening cognition
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
