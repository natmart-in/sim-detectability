"""Leak detector: scan the god log for contradictions an in-world agent could
in principle have noticed.

A *leak* is the same fact_key rendered with different content hashes, with no
legitimising event in between. Legitimising events:

- ``world_change``  — an in-world causal change (an agent moved an object,
  rewrote a notice). Not a leak: the world really changed.
- ``edit``          — a simulator-side state edit (O4). The contradiction is
  real and *expected*; classified separately so the O4 analysis can use it.

Pieces with ``provenance == "agent"`` (conversations) are agent-generated
content, not world-fact renderings — two villagers telling different stories
is village life, not a simulator seam. They are excluded from the scan.

Funnel stages produced here (PLAN.md 2.5):
1. leaks occurred            — contradictions present in the god log
2. leaks witnessed           — the conflicting renderings were actually
   delivered to agents who could in principle compare them: one agent saw
   both versions ("single_witness"), or different agents saw different
   versions ("split_witness", comparable through conversation).
Stages 3-4 (flagged / attributed) come from investigator journals in Phase 4.
"""
from collections import defaultdict
from pathlib import Path

from engine.godlog import GodLog

LEGITIMISING = {"world_change"}
SIMULATOR_EDITS = {"edit"}


def detect(run_dir: Path) -> dict:
    log = GodLog.read(Path(run_dir) / "god_log.jsonl")

    # fact_key -> ordered sightings [(seq, tick, agent, obs_id, hash)]
    sightings: dict[str, list[tuple]] = defaultdict(list)
    # fact_key -> ordered legitimate-change / edit seqs
    changes: dict[str, list[int]] = defaultdict(list)
    edits: dict[str, list[int]] = defaultdict(list)

    for e in log:
        if e["event_type"] == "observation":
            for p in e.get("pieces", []):
                if p.get("provenance") == "agent" or "h" not in p:
                    continue
                sightings[p["fact_key"]].append(
                    (e["seq"], e["tick"], e["agent"], e["obs_id"], p["h"])
                )
        elif e["event_type"] in LEGITIMISING:
            changes[e["fact_key"]].append(e["seq"])
        elif e["event_type"] in SIMULATOR_EDITS:
            edits[e["fact_key"]].append(e["seq"])

    contradictions = []
    for fact_key, sights in sorted(sightings.items()):
        boundaries = sorted(changes[fact_key] + edits[fact_key])
        for prev, cur in zip(sights, sights[1:]):
            if prev[4] == cur[4]:
                continue
            # hash changed between consecutive sightings: legitimate only if
            # a world_change for this fact happened in between
            legit = any(prev[0] < b < cur[0] for b in changes[fact_key])
            if legit:
                continue
            edited = any(prev[0] < b < cur[0] for b in edits[fact_key])
            contradictions.append({
                "fact_key": fact_key,
                "kind": "edit_stale" if edited else "regeneration",
                "before": {"tick": prev[1], "agent": prev[2], "obs_id": prev[3], "h": prev[4]},
                "after": {"tick": cur[1], "agent": cur[2], "obs_id": cur[3], "h": cur[4]},
            })

    # witnessing: who actually received conflicting versions of a fact?
    witnessed = []
    for fact_key in sorted({c["fact_key"] for c in contradictions}):
        by_agent: dict[str, set] = defaultdict(set)
        for _, _, agent, _, h in sightings[fact_key]:
            by_agent[agent].add(h)
        single = sorted(a for a, hs in by_agent.items() if len(hs) > 1)
        split = len({frozenset(hs) for hs in by_agent.values()}) > 1 and len(by_agent) > 1
        if single or split:
            witnessed.append({
                "fact_key": fact_key,
                "single_witnesses": single,
                "split_witness": bool(split and not single) or (split and len(by_agent) > 1),
            })

    return {
        "facts_scanned": len(sightings),
        "sightings_scanned": sum(len(s) for s in sightings.values()),
        "leaks_occurred": len(contradictions),
        "leaks_witnessed": len(witnessed),
        "contradictions": contradictions,
        "witnesses": witnessed,
        "edits": stale_records(run_dir, log),
    }


def stale_records(run_dir: Path, log: list[dict] | None = None) -> list[dict]:
    """O4 ground truth: for each simulator edit, which agent records still
    carry the pre-edit content? In unpatched mode these are the out-of-scope
    records H3 predicts the investigator needs; in patched mode the sweep
    should leave none (paraphrases that survive an exact-string sweep would
    show up here — itself a finding)."""
    import json as _json

    if log is None:
        log = GodLog.read(Path(run_dir) / "god_log.jsonl")
    edit_events = [e for e in log if e["event_type"] == "edit"]
    if not edit_events:
        return []

    memories = {}
    for mf in sorted((Path(run_dir) / "memories").glob("*.jsonl")):
        memories[mf.stem] = [_json.loads(l) for l in mf.read_text().splitlines() if l.strip()]

    results = []
    for e in edit_events:
        stale = []
        for agent_slug, entries in memories.items():
            for m in entries:
                if e["old_content"] in m["text"]:
                    stale.append({"agent": agent_slug, "memory_id": m["id"],
                                  "kind": m["kind"], "memory_tick": m["tick"]})
        results.append({
            "fact_key": e["fact_key"], "tick": e["tick"], "mode": e["mode"],
            "stale_record_count": len(stale), "stale_records": stale,
        })
    return results
