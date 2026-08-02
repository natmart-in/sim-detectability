# sim-detectability

The detectability-ceiling experiment: a small generative-agent village
("Littlefield") run the way a lazy but clever universe-owner might run ours —
lazy rendering, on-demand history, state edits — with an in-world investigator
trying to catch the cheats, and a god's-eye referee scoring detection exactly.
Full design: [PLAN.md](PLAN.md). Pre-registered hypotheses:
[PREREGISTRATION.md](PREREGISTRATION.md).

## Status

| Phase | State |
|---|---|
| 0 — Scaffold + deterministic smoke world | **done** (accept test: `tests/test_determinism.py`) |
| 1 — Living village (eager mode) | **done** — live acceptance run passed (retrieval 19/20; $0.0246/agent-day; extrapolates to ~$21 villager-layer cost for the primary sweep); human transcript review pending |
| 2 — Ground-truth plumbing (replay, leak detector) | not started |
| 3 — Optimisation suite (O1–O5) | not started |
| 4 — Investigator (Descartes) | not started |
| 5 — The matrix | not started |
| 6 — Analysis & write-up | not started |

## Layout

```
engine/     world, clock, RNG, god log, Perception API, LLM layer, tick loop
agents/     memory stream + retrieval, brains (scripted / LLM), prompts
referee/    scoring layer (skeleton; built in Phase 2+)
configs/    run configs (smoke, phase1_mock, phase1_live)
scripts/    retrieval_probe.py — acceptance probes against a real run
tests/      acceptance + guardrail tests
runs/       run artifacts (gitignored): god_log.jsonl, llm_log.jsonl,
            memories/*.jsonl, transcript.md, run_meta.json
```

## Quickstart

```sh
uv sync
uv run pytest                                             # all acceptance tests
uv run python -m engine.run --config configs/phase1_mock.yaml   # no API cost
# with ANTHROPIC_API_KEY set (or an `ant auth login` profile):
uv run python -m engine.run --config configs/phase1_live.yaml   # capped at $5
uv run python scripts/retrieval_probe.py runs/phase1_live-seed11
```

A killed run resumes without re-spending:
`--resume` re-drives the deterministic engine from tick 0, serving all prior
LLM completions from `llm_log.jsonl` (cache hits, $0), then continues live.

## Design decisions / deviations from PLAN.md

- **No sampling temperature.** `temperature`/`top_p`/`top_k` are rejected by
  claude-sonnet-5 / claude-opus-5 (2026 API). The plan's "temperature low for
  the engine, moderate for dialogue" is realised through prompts and the
  `effort` output config instead.
- **LLM at decision points, not every tick.** Villagers follow their daily
  plan procedurally; the LLM is called for daily planning, dialogue turns and
  nightly reflection (Stanford-style). This is what makes the budget feasible.
- **Resumability via replay, not state snapshots.** The engine is
  deterministic given (config, seed, llm_log); replaying is cheaper and
  simpler than checkpointing world state, and doubles as the Phase-2
  replay-from-logs mechanism.
- **Importance scoring is a heuristic by memory kind** (dialogue > document >
  activity > observation), not an LLM call — cheaper, deterministic, and
  sufficient at this fidelity. An LLM scorer can be slotted in if spot-checks
  degrade.
- **No wall-clock anywhere in logs.** God log, LLM log and memories carry sim
  ticks only, so pauses/retries/resumes leave no seam of our own making.

## Conduct note

Littlefield is designed as a decent place to live: mundane routines, no
scripted torment. Run logs are archived, not deleted.
