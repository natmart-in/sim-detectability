"""Phase 2 acceptance: a full run replays byte-identical from its own logs.

Re-drives an archived run in a temp dir using its config snapshot with its
llm_log.jsonl pre-seeded — every LLM call is a cache hit, so no API is touched
even for live-mode runs — then byte-compares god_log and memories.

    python scripts/replay_verify.py runs/phase1_live-seed11
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.engine import Runner  # noqa: E402


def replay(run_dir: Path, out_dir: Path) -> None:
    config = json.loads((run_dir / "config_snapshot.json").read_text(encoding="utf-8"))
    out_dir.mkdir(parents=True, exist_ok=True)
    src_llm = run_dir / "llm_log.jsonl"
    if src_llm.exists():
        shutil.copy(src_llm, out_dir / "llm_log.jsonl")
    runner = Runner(config, out_dir, run_id=run_dir.name)
    runner.run()
    if runner.llm is not None and runner.llm.live_calls > 0:
        raise AssertionError(
            f"replay made {runner.llm.live_calls} live LLM calls; cache should cover all"
        )


def verify(run_dir: Path) -> bool:
    run_dir = Path(run_dir)
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "replay"
        replay(run_dir, out)
        ok = True
        pairs = [(run_dir / "god_log.jsonl", out / "god_log.jsonl")]
        pairs += [
            (m, out / "memories" / m.name)
            for m in sorted((run_dir / "memories").glob("*.jsonl"))
        ]
        for orig, rep in pairs:
            same = rep.exists() and orig.read_bytes() == rep.read_bytes()
            print(f"{'IDENTICAL' if same else 'DIFFERS  '}  {orig.relative_to(run_dir)}")
            ok &= same
    return ok


if __name__ == "__main__":
    ok = verify(Path(sys.argv[1]))
    print("\nreplay", "PASSED: byte-identical" if ok else "FAILED")
    sys.exit(0 if ok else 1)
