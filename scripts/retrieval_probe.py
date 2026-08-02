"""Phase 1 acceptance: retrieval spot-checks against a *real* run.

Builds 20 probes from the run's own ground truth (its god log) and checks the
agent's memory retrieval surfaces the expected memory in the top 3.

    python scripts/retrieval_probe.py runs/phase1_live-seed11
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.memory import MemoryStream  # noqa: E402
from engine.engine import slug  # noqa: E402


def build_probes(run_dir: Path) -> list[tuple[str, str, frozenset]]:
    """Returns (agent, query, acceptable_obs_ids) triples derived from god log.

    A retrieval hit is any top-3 memory citing an observation with the same
    focus — e.g. for "my time at the cafe", any cafe observation by that agent
    counts, not one arbitrary designated instance.
    """
    log = [json.loads(l) for l in (run_dir / "god_log.jsonl").read_text().splitlines()]
    meta = json.loads((run_dir / "run_meta.json").read_text())
    agents = set(meta["agents"])

    # (agent, focus) -> all obs ids with that focus
    by_focus: dict[tuple[str, str], set] = {}
    for e in log:
        if e["event_type"] == "observation" and e["agent"] in agents:
            by_focus.setdefault((e["agent"], e["focus"]), set()).add(e["obs_id"])

    # positions per tick, for judging location probes
    positions = {e["tick"]: e["positions"] for e in log if e["event_type"] == "tick_end"}

    probes = []
    for (agent, focus), ids in sorted(by_focus.items()):
        kind, _, target = focus.partition(":")
        if kind == "conversation":
            probes.append((agent, f"my conversation with {target}", frozenset(ids), None))
        elif kind == "document":
            probes.append((agent, f"reading the {target.replace('_', ' ')}", frozenset(ids), None))
        elif kind == "location":
            # any non-plan memory formed while at the location also counts
            probes.append((agent, f"my time at the {target.replace('_', ' ')}",
                           frozenset(ids), (target, positions)))
    return probes


def main(run_dir: Path, n_probes: int = 20):
    meta = json.loads((run_dir / "run_meta.json").read_text())
    last_tick = meta["ticks_completed"]
    probes = build_probes(run_dir)
    # deterministic spread: take every k-th probe to reach n_probes
    if len(probes) > n_probes:
        step = len(probes) / n_probes
        probes = [probes[int(i * step)] for i in range(n_probes)]

    streams = {
        name: MemoryStream.load(name, run_dir / "memories" / f"{slug(name)}.jsonl")
        for name in meta["agents"]
    }
    hits, results = 0, []
    for agent, query, acceptable, loc_ctx in probes:
        top3 = streams[agent].retrieve(query, last_tick, k=3)
        ok = any(set(e.obs_ids) & acceptable for e in top3)
        if not ok and loc_ctx:
            target, positions = loc_ctx
            ok = any(
                e.kind != "plan" and positions.get(e.tick, {}).get(agent) == target
                for e in top3
            )
        hits += ok
        results.append((ok, agent, query, sorted(acceptable)[0]))

    for ok, agent, query, expected in results:
        print(f"{'HIT ' if ok else 'MISS'}  {agent:16s}  {query!r:55s} -> {expected}…")
    rate = hits / len(results) if results else 0.0
    print(f"\n{hits}/{len(results)} probes hit ({rate:.0%}); acceptance bar is 80%")
    return 0 if rate >= 0.8 else 1


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
