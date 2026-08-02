"""CLI entry point.

    python -m engine.run --config configs/phase1_live.yaml
    python -m engine.run --config configs/phase1_live.yaml --resume   # after a kill

Fresh runs refuse to touch an existing run directory unless --resume (keeps
llm_log.jsonl, replays without re-spending) or --force (wipes) is given.
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

import yaml

from .engine import Runner


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--out", default=None)
    ap.add_argument("--resume", action="store_true",
                    help="re-drive the run, serving prior LLM calls from llm_log.jsonl")
    ap.add_argument("--force", action="store_true", help="wipe an existing run dir")
    args = ap.parse_args(argv)

    cfg_path = Path(args.config)
    config = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    out = Path(args.out) if args.out else Path("runs") / f"{cfg_path.stem}-seed{config['seed']}"

    if out.exists() and any(out.iterdir()):
        if args.force:
            shutil.rmtree(out)
        elif args.resume:
            for p in out.iterdir():
                if p.name != "llm_log.jsonl":
                    shutil.rmtree(p) if p.is_dir() else p.unlink()
        else:
            sys.exit(f"run dir {out} exists; use --resume or --force")

    runner = Runner(config, out)
    runner.run()
    meta = json.loads((out / "run_meta.json").read_text(encoding="utf-8"))
    print(json.dumps(meta, indent=2, sort_keys=True))
    print(f"\nrun dir: {out}")
    if meta["status"] != "completed":
        sys.exit(2)


if __name__ == "__main__":
    main()
