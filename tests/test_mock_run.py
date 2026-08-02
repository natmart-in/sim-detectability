"""Phase 1 plumbing: a full 2-sim-day village run over the mock LLM.

Checks structural coherence properties that must also hold for live runs:
- run completes; every agent plans each morning and reflects each evening
- conversations only happen between co-located agents (checked vs god log)
- dialogue memories cite observation ids that exist in the god log
- agents follow their plans (each agent visits their planned locations)
"""
import json
from pathlib import Path

import yaml

from engine.engine import Runner

ROOT = Path(__file__).resolve().parents[1]


def test_two_day_mock_run(tmp_path):
    config = yaml.safe_load((ROOT / "configs" / "phase1_mock.yaml").read_text())
    out = tmp_path / "run"
    Runner(config, out).run()

    meta = json.loads((out / "run_meta.json").read_text())
    assert meta["status"] == "completed"
    assert meta["ticks_completed"] == 128
    assert meta["llm"]["spent_usd"] < 5.0

    log = [json.loads(l) for l in (out / "god_log.jsonl").read_text().splitlines()]
    agents = set(meta["agents"])
    assert len(agents) == 5

    # plans: every agent, both mornings
    plans = [e for e in log if e["event_type"] == "plan"]
    assert len(plans) == 10
    # reflections: every agent, both evenings
    refls = [e for e in log if e["event_type"] == "reflection"]
    assert len(refls) == 10

    # conversations happened, and only between co-located agents
    dialogues = [e for e in log if e["event_type"] == "dialogue"]
    assert dialogues, "no conversations in 2 sim-days"
    tick_positions = {e["tick"]: e["positions"] for e in log if e["event_type"] == "tick_end"}
    for d in dialogues:
        pos = tick_positions[d["tick"]]
        a, b = d["participants"]
        assert pos[a] == pos[b] == d["location"], f"dialogue between non-co-located agents: {d}"

    # dialogue memories cite obs ids that exist in the god log
    obs_ids = {e["obs_id"] for e in log if e["event_type"] == "observation"}
    cited = 0
    for mem_file in (out / "memories").glob("*.jsonl"):
        for line in mem_file.read_text().splitlines():
            m = json.loads(line)
            for oid in m["obs_ids"]:
                assert oid in obs_ids, f"memory cites unknown obs id {oid}"
                cited += 1
    assert cited > 0

    # agents executed their plans: for each plan step long enough to reach,
    # the agent was at the planned location at some tick
    moves_ok = 0
    for p in plans:
        agent = p["agent"]
        day0 = (p["tick"] // 64) * 64
        for step in p["steps"]:
            if step["end_tick"] - step["start_tick"] < 8:
                continue  # short steps may be spent mostly walking
            there = any(
                tick_positions[t][agent] == step["location"]
                for t in range(day0 + step["start_tick"], day0 + step["end_tick"])
                if t in tick_positions
            )
            assert there, f"{agent} never reached {step['location']} for {step['activity']}"
            moves_ok += 1
    assert moves_ok > 20

    transcript = (out / "transcript.md").read_text()
    assert "conversation at" in transcript and "Evening reflections" in transcript
