"""Phase 0 acceptance: the no-LLM smoke world ticks 100 steps deterministically
twice with identical logs. Also checks the mock-LLM path stays deterministic."""
from pathlib import Path

import yaml

from engine.engine import Runner

ROOT = Path(__file__).resolve().parents[1]


def _run(config: dict, out: Path) -> Path:
    Runner(config, out).run()
    return out


def _load(name: str) -> dict:
    return yaml.safe_load((ROOT / "configs" / name).read_text(encoding="utf-8"))


def _assert_identical(a: Path, b: Path):
    assert (a / "god_log.jsonl").read_bytes() == (b / "god_log.jsonl").read_bytes()
    mems_a = sorted((a / "memories").glob("*.jsonl"))
    mems_b = sorted((b / "memories").glob("*.jsonl"))
    assert [m.name for m in mems_a] == [m.name for m in mems_b] and mems_a
    for fa, fb in zip(mems_a, mems_b):
        assert fa.read_bytes() == fb.read_bytes(), fa.name


def test_smoke_world_100_ticks_deterministic(tmp_path):
    config = _load("smoke.yaml")
    assert config["ticks"] == 100 and config["llm"]["mode"] == "scripted"
    a = _run(config, tmp_path / "a")
    b = _run(config, tmp_path / "b")
    _assert_identical(a, b)
    ticks = [l for l in (a / "god_log.jsonl").read_text().splitlines()
             if '"event_type":"tick_end"' in l]
    assert len(ticks) == 100


def test_mock_llm_run_deterministic(tmp_path):
    config = _load("phase1_mock.yaml")
    config["ticks"] = 64  # one sim-day is enough for the determinism check
    a = _run(config, tmp_path / "a")
    b = _run(config, tmp_path / "b")
    _assert_identical(a, b)
