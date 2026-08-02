"""Referee report CLI (offline, after a run — never touches the in-world layer).

    python -m referee.report runs/phase1_live-seed11

Phase 2 scope: the leak-detector funnel stages 1-2. The verdict scorer and
apophenia counter (stages 3-4) land with the investigator in Phase 4.
"""
import json
import sys
from pathlib import Path

from .leak_detector import detect
from .verdict import score


def main(argv=None):
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        sys.exit("usage: python -m referee.report <run_dir>")
    run_dir = Path(args[0])
    report = detect(run_dir)
    if (run_dir / "journals").exists():
        report["verdict"] = score(run_dir)
    out = run_dir / "referee_report.json"
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    print(f"\nreport written to {out}")


if __name__ == "__main__":
    main()
