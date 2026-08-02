"""Phase 2 acceptance: a full run replays byte-identical from logs alone,
with zero live LLM calls."""
import shutil
from pathlib import Path

import yaml

from engine.engine import Runner

ROOT = Path(__file__).resolve().parents[1]


def test_replay_byte_identical_without_live_calls(tmp_path):
    config = yaml.safe_load((ROOT / "configs" / "phase1_mock.yaml").read_text())
    config["ticks"] = 96
    orig = tmp_path / "orig"
    Runner(config, orig).run()

    # Replay: fresh dir seeded only with the LLM log; runner in the same mode
    # must serve everything from cache.
    rep = tmp_path / "replay"
    rep.mkdir()
    shutil.copy(orig / "llm_log.jsonl", rep / "llm_log.jsonl")
    runner = Runner(config, rep, run_id=orig.name)
    runner.run()
    assert runner.llm.live_calls == 0, "replay should be 100% cache hits"
    assert runner.llm.cache_hits == runner.llm.calls > 0

    assert (orig / "god_log.jsonl").read_bytes() == (rep / "god_log.jsonl").read_bytes()
    for m in sorted((orig / "memories").glob("*.jsonl")):
        assert m.read_bytes() == (rep / "memories" / m.name).read_bytes(), m.name
