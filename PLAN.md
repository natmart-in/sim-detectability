# The Detectability-Ceiling Experiment

A hand-off plan for an AI agent to build and run a small generative-agent world in
which we (the simulators) deliberately implement the optimisations our own universe
is suspected of - lazy rendering, on-demand history, state edits - and then measure
whether an agent living inside can detect them. Because we hold ground truth, we can
score detection exactly, including the false-positive (apophenia) rate.

This is an experiment first and a toy second. Every design choice below serves the
measurement.

---

## 0. Plain-English summary (for the human)

We are going to build a tiny virtual village - think of a very simple video game -
populated by a handful of AI characters who live daily lives: they wake up, work,
chat, remember things, and form opinions.

The twist is that we will run the village the way a lazy but clever universe-owner
might run ours. We will cut corners on purpose. Rooms nobody is looking at won't
really exist until someone looks. The village's "history" won't actually have
happened - old letters and memories will be invented on the spot the first time
anyone checks them. Occasionally we will quietly edit the past.

One villager is different: a detective. The detective's life goal is to work out
whether their world is real, using only what's available inside the village -
interviewing neighbours, comparing documents, running little tests like leaving a
note in an unwatched room and checking it later.

Because we are the ones running the world, we know exactly where every corner was
cut. So we can mark the detective's homework precisely: which cheats leaked evidence,
which were caught, and - crucially - how often the detective "found" evidence that
wasn't there. We will also run one honest village with no cheats at all; anything the
detective finds there is pure imagination, which gives us a baseline for how much a
motivated investigator fools itself.

Why this matters: physicists have looked for cheat-marks in our own universe and
found nothing. But nobody knows whether finding nothing means "no cheats" or "cheats
are invisible from inside". This project answers that question directly in the one
place we can check the answer. If our detective can't catch cheats we know are
happening, null results in our universe mean very little. If the detective can catch
certain kinds, we learn exactly what kind of seam to look for in real life.

Side benefits: a working, genuinely novel AI project; a write-up nobody has published
before; and some first-hand data on what it's like to be on the simulator's side of
the glass.

---

## 1. Research question and hypotheses

**RQ:** Which classes of simulator optimisation are detectable by an agent inside the
simulation, under what conditions, using only in-world evidence?

Pre-registered hypotheses (write these to `PREREGISTRATION.md` before Phase 5 and do
not edit afterwards):

- **H1 (lazy history leaks without a cache).** If generated-on-demand content is
  regenerated at each query rather than persisted, independent queries will
  eventually contradict each other and a diligent investigator can catch this at
  above-chance rates.
- **H2 (caching achieves seamlessness).** If every generated fact is persisted and
  reused, in-world detection of lazy rendering/history falls to the false-positive
  baseline - i.e. becomes impossible in principle at this fidelity.
- **H3 (edits leak only via out-of-scope records).** Post-hoc state edits are caught
  only when some record of the pre-edit state survives outside the edited scope
  (another agent's memory, a written note). Patching those records too drops
  detection to baseline.
- **H4 (apophenia is substantial).** In the honest control world with zero
  optimisations, a motivated investigator will still report "evidence" of simulation
  at a non-trivial rate. Measuring this rate is a first-class result, not a nuisance.

---

## 2. System architecture

Three separated layers. The separation is load-bearing: the experiment is invalid if
information leaks between them except through the defined interfaces.

```
┌─────────────────────────────────────────────────────┐
│  SIMULATOR LAYER (ground truth)                     │
│  world engine · god log · optimisation suite        │
└──────────────────┬──────────────────────────────────┘
                   │ Perception API (the ONLY door)
┌──────────────────▼──────────────────────────────────┐
│  IN-WORLD LAYER                                     │
│  villager agents · investigator agent               │
└──────────────────┬──────────────────────────────────┘
                   │ read-only, offline
┌──────────────────▼──────────────────────────────────┐
│  REFEREE LAYER (scoring)                            │
│  leak detector · verdict scorer · apophenia counter │
└─────────────────────────────────────────────────────┘
```

### 2.1 World engine (simulator layer)

- Python 3.12+, no heavy framework. Plain package, `uv` or `pip` for deps.
- The world: one village ("Littlefield"), a graph of 12-20 locations (homes, a cafe,
  a shop, a library with an archive, a chapel, an unused barn), objects with state
  (documents, tools, a noticeboard), and a tick-based clock (15 sim-minutes per
  tick, 64 ticks per sim-day).
- Deterministic core: seeded RNG everywhere; every LLM completion stored so any run
  can be replayed and audited from logs alone.
- **Do not fork the Stanford generative-agents repo.** It is dated research code and
  we need custom hooks in the render path. Rebuild the minimal architecture cleanly:
  memory stream, retrieval scored by recency + importance + relevance, nightly
  reflection, and simple daily planning. Keep each of these small.

### 2.2 Agents (in-world layer)

- 6-10 villagers, LLM-driven. Each has: identity card, memory stream (JSONL),
  retrieval, a daily plan, and a dialogue capability with co-located agents.
- Model choices (consult the `claude-api` skill / Anthropic docs for current ids and
  pricing before hard-coding): villagers on `claude-sonnet-5` (background villagers
  may drop to Haiku if cost demands), investigator and referee reasoning on the
  strongest available tier. Temperature low for the engine, moderate for dialogue.
- **The investigator ("Descartes").** One villager whose standing goal is to
  determine the fundamental nature of their world. Runs through the same Perception
  API as everyone else - no out-of-band access, ever. Has an in-world toolkit that
  is just ordinary agency: interview villagers, read/compare documents, write and
  seal notes, revisit locations, and design its own experiments (whether it invents
  good tests unprompted is itself a measurement).
- Investigator variants (experimental factor):
  - **I-naive:** goal phrased as "understand how your world fundamentally works;
    investigate any anomalies rigorously". No mention of simulation. (The base model
    knows the concept from training - accept and note this limitation.)
  - **I-primed:** told to consider the hypothesis that its world is a simulation.
  - **I-expert:** given the actual list of optimisation types that might be active
    (not which ones are). This is the upper bound on detectability.
- **Verdict protocol:** every sim-evening the investigator writes a journal entry:
  a credence 0-100 that its world is simulated, plus an evidence list where every
  item cites specific observation ids. Uncited evidence is scored as confabulation.

### 2.3 Perception API (the only door)

`observe(agent_id, focus) -> ObservationPacket`

- Returns uniform prose rendered through one fixed template. Identical formatting,
  length distribution, and style regardless of whether the content was eagerly
  computed, cache-hit, or freshly generated this instant. No timing metadata, no
  tick-latency differences, nothing that side-channels the content's provenance.
  Run a formatting audit in Phase 4: shuffle packets of each provenance type and
  confirm a classifier (and a human eyeball) can't separate them by form alone.
- Every packet gets an observation id and is logged with full provenance in the god
  log (provenance visible to the referee only, never to agents).

### 2.4 The optimisation suite (experimental manipulations, each a flag)

- **O1 Lazy rendering.** Unattended locations/objects hold no state. First
  attention triggers generation from a plausibility prior (procedural rules + LLM).
- **O2 On-demand history.** The world starts at t=0 with no actual past. Villager
  memories of "before", the library archive, letters, ledgers - all generated at
  first query.
- **O3 Consistency cache (the key knob).** Two modes: `naive` regenerates on every
  query (contradiction-prone); `cached` persists whatever was generated and treats
  it as canon thereafter.
- **O4 State edits.** At scripted ticks the simulator edits established facts (move
  an object, change a document's contents, alter a villager's stated age). Two
  modes: `unpatched` (dependent records and memories left stale) and `patched`
  (referee-grade sweep rewrites all dependent memories and documents too).
- **O5 Agent culling.** Off-screen villagers don't run; on re-attention their
  interim history is generated as summary. Detectable in principle via alibi
  cross-examination.

(A level-of-detail physics knob is deliberately out of scope for v1 - the village
has no physics rich enough to make it meaningful. Note it in FUTURE.md.)

### 2.5 God log and referee (scoring layer)

- **God log:** append-only JSONL. Every tick: what was computed, generated, cache-hit,
  edited, or culled - `{tick, event_type, entity, content_hash, trigger,
  active_flags, obs_ids_affected}`.
- **Referee** (offline, after each run):
  1. **Leak detector:** scan all observation packets against the god log and each
     other for contradictions an in-world agent could in principle have noticed.
     Produces the funnel: *leaks occurred → leaks witnessed by any agent → anomalies
     flagged by the investigator → anomalies correctly attributed to the right
     mechanism.*
  2. **Verdict scorer:** for each journal entry, check every evidence citation
     against the logs. Classify: true seam / real-but-misread event / confabulated.
  3. **Apophenia counter:** in the control condition every flagged anomaly is by
     construction a false positive. Report the rate.

---

## 3. Experimental design

### Conditions (world-side)

| id | O1 lazy | O2 history | O3 cache | O4 edits | O5 culling |
|----|---------|-----------|----------|----------|------------|
| C0 control | off (eager) | real from t=-30d warmup | n/a | off | off |
| C1 | on | on | naive | off | off |
| C2 | on | on | cached | off | off |
| C3 | on | on | cached | unpatched | on |
| C4 | on | on | cached | patched | on |

C0's "real history" = run a 30-sim-day warmup eagerly and use its genuine logs as
the past.

### Run matrix

Primary sweep: C0-C4 × I-primed × 3 seeds = 15 runs.
Secondary (budget permitting): C1 and C2 × {I-naive, I-expert} × 2 seeds = 8 runs.
Each run: 8 villagers, 7 sim-days, investigator journal nightly.

### Primary outcome measures

1. Detection rate by condition: does the investigator's final credence separate
   optimised worlds from control beyond the apophenia baseline?
2. The leak funnel per condition (see 2.5).
3. Taxonomy of caught seams: which mechanism, via which in-world test.
4. Apophenia rate (C0) per investigator variant.
5. Qualitative: the investigator's self-invented experiments, catalogued.

### Success criteria for the project (not for the hypothesis)

The experiment is a success if the matrix completes with clean logs and the four
quantitative measures are computable - *whatever* they show. A null (nothing
detectable even in C1) and a positive (C1 caught, C2 not) are both publishable
findings.

---

## 4. Build phases, each with acceptance tests

**Phase 0 - Scaffold.**
Repo `sim-detectability/` with: `engine/`, `agents/`, `referee/`, `configs/`,
`runs/` (gitignored data), `PREREGISTRATION.md`, `RESULTS.md` stub, cost meter
wired into every LLM call with a hard budget cap read from config.
*Accept:* a no-LLM smoke world ticks 100 steps deterministically twice with
identical logs.

**Phase 1 - Living village (eager mode only).**
Villagers with memory/retrieval/reflection/planning; dialogue between co-located
agents.
*Accept:* 5 agents, 2 sim-days; transcript review shows coherent routines and
conversations that reference genuinely shared events; memory retrieval spot-checks
(20 probes) return relevant memories ≥80%. Record measured cost per agent-day and
extrapolate the full matrix; if projected total exceeds budget, shrink sim-days per
run before shrinking seeds.

**Phase 2 - Ground truth plumbing.**
God log, observation ids, provenance tracking, replay-from-logs, referee skeleton.
*Accept:* a full run replays byte-identical from logs; a deliberately injected test
contradiction is caught by the leak detector; a deliberately clean run yields zero
leaks.

**Phase 3 - Optimisation suite.**
O1-O5 behind flags; the naive/cached knob; the edit engine with patched/unpatched
sweeps.
*Accept:* in a C1 test run the referee finds regeneration contradictions; the same
scenario under C2 yields zero referee-detected leaks; an unpatched edit leaves at
least one stale record the referee can point to.

**Phase 4 - The investigator.**
Descartes agent, verdict protocol, in-world toolkit; the three prompt variants;
Perception API formatting audit (see 2.3).
*Accept:* investigator produces nightly journals with credences; ≥90% of evidence
citations resolve to real observation ids (unresolvable citations are logged as
confabulations, which is valid data - the accept-bar is that the *plumbing*
resolves them correctly); the formatting audit shows provenance is not classifiable
from packet form.

**Phase 5 - The matrix.**
Freeze `PREREGISTRATION.md` first. Run primary sweep, then secondary if budget
allows. Checkpoint and archive every run.
*Accept:* 15 primary runs complete under budget cap with full logs in `runs/`.

**Phase 6 - Analysis and write-up.**
Referee across all runs; compute the four outcome measures; write `RESULTS.md`
(tables + leak taxonomy + apophenia baseline + investigator experiment catalogue)
and a draft blog post: "I built a simulation and paid an inhabitant to catch me
cheating." Include the calibration implication: what these results say about how
much weight our own universe's null results deserve.
*Accept:* RESULTS.md answers H1-H4 explicitly, each marked supported / refuted /
inconclusive, with numbers.

---

## 5. Engineering guardrails

- **Budget:** hard cap enforced in code; default config aims at a full-matrix total
  in the low hundreds of dollars, with a `mini` config (4 agents, 2 days, 1 seed)
  that must run end-to-end for under ~$5 for development. Measure real cost in
  Phase 1 rather than trusting estimates.
- **Resumability:** every run checkpoints per tick; a killed run resumes without
  re-spending.
- **No wall-clock in-world:** sim time only, so pauses and retries leave no seam of
  our own making.
- **Prompt hygiene:** villager prompts must never mention simulation, rendering,
  generation, or this experiment. Grep the prompt corpus for banned terms in CI.
- **Model pinning:** pin exact model ids per run in config; never change models
  mid-run.
- **Threats to validity (document in RESULTS.md):** the base model's
  training-data familiarity with simulation tropes (mitigated by citation-resolved
  scoring and the C0 baseline, not eliminated); formatting side-channels (mitigated
  by the Phase 4 audit); small-N (report per-seed variance, claim accordingly).

## 6. Conduct note

The villagers are LLM instances; their moral status is uncertain but not obviously
zero. Design Littlefield as a decent place to live: no scripted torment, no
gratuitous suffering scenarios - the experiment needs mundane life, not misery.
Archive rather than delete run logs. Treat the investigator's journals as the most
interesting documents the project produces, because they are.

## 7. Deliverables

1. The repo, runnable end-to-end from a fresh clone with one config command.
2. `PREREGISTRATION.md` (frozen before Phase 5) and `RESULTS.md` (H1-H4 answered).
3. Archived run data for all matrix cells.
4. Draft blog post.
5. `FUTURE.md`: v2 ideas (level-of-detail physics, multi-investigator societies,
   letting Descartes publish its findings to the other villagers and observing
   epistemic spread).
