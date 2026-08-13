"""Incrementally archive completed matrix runs into git.

    python scripts/archive_runs.py           # one pass over runs/matrix
    python scripts/archive_runs.py --watch   # poll until the sweep prints [end ]

Each completed run in runs/matrix/ is compressed to archive/<run_id>.tar.zst
and committed (with the current manifest.jsonl) and pushed. runs/ stays
gitignored; archive/ is the durable copy — deliverable 3 of PLAN.md.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MATRIX_DIR = ROOT / "runs" / "matrix"
ARCHIVE_DIR = ROOT / "archive"
CONSOLE_LOG = MATRIX_DIR / "matrix_console.log"
POLL_SECONDS = 120


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(ROOT), *args],
                          capture_output=True, text=True)


def completed_runs() -> list[Path]:
    out = []
    for d in sorted(MATRIX_DIR.glob("*/")):
        meta = d / "run_meta.json"
        if meta.exists() and json.loads(meta.read_text()).get("status") == "completed":
            out.append(d)
    return out


def archive_run(run_dir: Path) -> Path | None:
    """Compress one run dir; returns the archive path if newly created."""
    dest = ARCHIVE_DIR / f"{run_dir.name}.tar.zst"
    if dest.exists():
        return None
    tmp = ARCHIVE_DIR / f".tmp-{run_dir.name}.tar.zst"
    subprocess.run(
        ["tar", "--zstd", "-cf", str(tmp), "-C", str(MATRIX_DIR), run_dir.name],
        check=True)
    os.replace(tmp, dest)
    return dest


def one_pass() -> bool:
    """Archive anything new; commit + push if the tree changed. True if it did."""
    ARCHIVE_DIR.mkdir(exist_ok=True)
    new = [p for p in (archive_run(d) for d in completed_runs()) if p]
    manifest = MATRIX_DIR / "manifest.jsonl"
    if manifest.exists():
        shutil.copy2(manifest, ARCHIVE_DIR / "manifest.jsonl")
    git("add", "archive", "scripts/archive_runs.py")
    if git("diff", "--cached", "--quiet").returncode == 0:
        return False
    names = ", ".join(p.stem.removesuffix(".tar") for p in new) or "manifest update"
    msg = (f"Archive matrix runs: {names}\n\n"
           "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>")
    r = git("commit", "-m", msg)
    print(r.stdout.strip() or r.stderr.strip(), flush=True)
    push = git("push")
    if push.returncode != 0:
        print(f"[warn] push failed (will retry next pass): {push.stderr.strip()}",
              flush=True)
    return True


def sweep_ended() -> bool:
    return CONSOLE_LOG.exists() and "[end ]" in CONSOLE_LOG.read_text()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch", action="store_true",
                    help="poll until the sweep's console log prints [end ]")
    args = ap.parse_args()
    while True:
        if one_pass():
            print(f"[arch] archive up to date "
                  f"({len(list(ARCHIVE_DIR.glob('*.tar.zst')))} runs)", flush=True)
        if not args.watch:
            break
        if sweep_ended():
            one_pass()
            print("[arch] sweep ended; final pass done", flush=True)
            break
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    sys.exit(main())
