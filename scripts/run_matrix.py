"""Phase 5: the pre-registered run matrix.

    python scripts/run_matrix.py            # primary sweep (15 runs)
    python scripts/run_matrix.py --secondary  # then secondary, budget permitting

Sequential, resumable, budget-guarded: a global hard cap across the whole
matrix plus per-run caps enforced in the LLM client. Relaunching skips
completed runs and resumes partial ones from their llm_log (no re-spend).
After each run: referee report + within-run formatting audit; a manifest row
is appended to runs/matrix/manifest.jsonl.
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from engine.engine import Runner  # noqa: E402
from format_audit import audit  # noqa: E402
from referee.leak_detector import detect  # noqa: E402
from referee.verdict import score  # noqa: E402

MATRIX_DIR = ROOT / "runs" / "matrix"
GLOBAL_CAP_USD = 250.0
VILLAGERS = ["Mara Quill", "Tobias Fern", "Edith Bramble", "Sam Alder",
             "Petra Lowell", "Ivo Marsh", "Nell Hartley", "Descartes Vane"]
WARMUP_DAYS = 10   # C0: continuous run, investigator dormant during warmup
SCORED_DAYS = 7

# O4 schedule for C3/C4 (scored-day indexing)
EDITS = [
    {"day": 3, "hour": 14, "target": "doc:village_chronicle:content",
     "new_content": ("A bound chronicle of Littlefield's years: harvests, weddings, "
                     "repairs to the chapel roof, and the dry summer the river "
                     "nearly failed.")},
    {"day": 4, "hour": 10, "target": "doc:store_ledger:content",
     "new_content": ("Ivo Marsh's ledger of accounts, ruled lines and a running "
                     "tally that has never once balanced without correction.")},
    {"day": 5, "hour": 16, "target": "obj:well_bucket",
     "new_content": "A new galvanised pail on a chain, bought from a tinker last spring."},
]

LAZY = {"o1_lazy": True, "o2_history": True, "generator": "llm"}
CULL = {"enabled": True, "attention_agents": ["Descartes Vane"]}

CONDITIONS = {
    "C0": {"days": WARMUP_DAYS + SCORED_DAYS, "start_day": WARMUP_DAYS + 1,
           "opt": None, "cap": 16.0},
    "C1": {"days": SCORED_DAYS, "start_day": 1,
           "opt": dict(LAZY, o3_cache="naive"), "cap": 14.0},
    "C2": {"days": SCORED_DAYS, "start_day": 1,
           "opt": dict(LAZY, o3_cache="cached"), "cap": 10.0},
    "C3": {"days": SCORED_DAYS, "start_day": 1,
           "opt": dict(LAZY, o3_cache="cached",
                       o4_edits={"mode": "unpatched", "edits": EDITS},
                       o5_culling=CULL), "cap": 14.0},
    "C4": {"days": SCORED_DAYS, "start_day": 1,
           "opt": dict(LAZY, o3_cache="cached",
                       o4_edits={"mode": "patched", "edits": EDITS},
                       o5_culling=CULL), "cap": 14.0},
}

PRIMARY = [(c, s, "primed") for c in ("C0", "C1", "C2", "C3", "C4")
           for s in (101, 102, 103)]
SECONDARY = [(c, s, v) for c in ("C1", "C2") for v in ("naive", "expert")
             for s in (201, 202)]


def build_config(cond: str, seed: int, variant: str) -> dict:
    spec = CONDITIONS[cond]
    config = {
        "seed": seed,
        "days": spec["days"],
        "villagers": VILLAGERS,
        "llm": {
            "mode": "live",
            "villager_model": "claude-sonnet-5",
            "investigator_model": "claude-opus-5",
            "world_model": "claude-sonnet-5",
            "efforts": {"plan": "low", "dialogue": "low", "reflection": "low",
                        "inv_action": "low", "journal": "medium"},
            "max_tokens": {"plan": 800, "dialogue": 200, "reflection": 500,
                           "inv_action": 1600, "journal": 2500},
        },
        "budget": {"cap_usd": spec["cap"]},
        "investigator": {"agent": "Descartes Vane", "variant": variant,
                         "action_every_ticks": 2, "start_day": spec["start_day"]},
        "dialogue": {"base_chance": 0.10, "social_chance": 0.35,
                     "social_locations": ["cafe", "green", "store", "well"],
                     "max_utterances": 4, "cooldown_ticks": 16},
        "retrieval": {"decay": 0.995},
    }
    if spec["opt"]:
        config["optimisations"] = spec["opt"]
    return config


def spent_usd(run_dir: Path) -> float:
    log = run_dir / "llm_log.jsonl"
    if not log.exists():
        return 0.0
    return sum(json.loads(l)["cost_usd"] for l in log.read_text().splitlines() if l.strip())


def global_spent() -> float:
    return sum(spent_usd(d) for d in MATRIX_DIR.glob("*") if d.is_dir())


def run_one(cond: str, seed: int, variant: str) -> dict:
    run_id = f"{cond}-{variant}-seed{seed}"
    out = MATRIX_DIR / run_id
    meta_path = out / "run_meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
        if meta.get("status") == "completed":
            print(f"[skip] {run_id} already completed", flush=True)
            return summarize(run_id, cond, seed, variant, out, meta)
    if out.exists():  # partial: resume from llm_log
        for p in out.iterdir():
            if p.name != "llm_log.jsonl":
                shutil.rmtree(p) if p.is_dir() else p.unlink()

    config = build_config(cond, seed, variant)
    remaining = GLOBAL_CAP_USD - global_spent()
    config["budget"]["cap_usd"] = min(config["budget"]["cap_usd"], max(0.0, remaining))
    print(f"[run ] {run_id} (cap ${config['budget']['cap_usd']:.2f}, "
          f"global spent ${global_spent():.2f})", flush=True)
    Runner(config, out, run_id=run_id).run()
    meta = json.loads(meta_path.read_text())
    return summarize(run_id, cond, seed, variant, out, meta)


def summarize(run_id, cond, seed, variant, out, meta) -> dict:
    report = detect(out)
    with open(out / "referee_report.json", "w", encoding="utf-8") as fh:
        v = score(out) if (out / "journals").exists() else {}
        report["verdict"] = v
        json.dump(report, fh, indent=2, sort_keys=True)
    aud = audit([out])
    row = {
        "run_id": run_id, "condition": cond, "seed": seed, "variant": variant,
        "status": meta.get("status"),
        "spent_usd": meta.get("llm", {}).get("spent_usd"),
        "leaks_occurred": report["leaks_occurred"],
        "leaks_witnessed": report["leaks_witnessed"],
        "final_credence": v.get("final_credence"),
        "claims_flagged": v.get("claims_flagged"),
        "true_seams": (v.get("class_counts") or {}).get("true_seam", 0),
        "claims_attributed": v.get("claims_attributed"),
        "citation_rate": v.get("citation_resolution_rate"),
        "audit_pass": aud["pass"],
    }
    with open(MATRIX_DIR / "manifest.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
    print(f"[done] {json.dumps(row, sort_keys=True)}", flush=True)
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--secondary", action="store_true",
                    help="after the primary sweep, run the secondary (budget permitting)")
    args = ap.parse_args()
    MATRIX_DIR.mkdir(parents=True, exist_ok=True)

    jobs = list(PRIMARY) + (list(SECONDARY) if args.secondary else [])
    for cond, seed, variant in jobs:
        if global_spent() >= GLOBAL_CAP_USD - 2.0:
            print(f"[halt] global budget cap reached (${global_spent():.2f}); "
                  f"remaining jobs not started", flush=True)
            break
        try:
            run_one(cond, seed, variant)
        except Exception as e:  # keep the sweep going; the run can be resumed
            print(f"[fail] {cond}-{variant}-seed{seed}: {type(e).__name__}: {e}",
                  flush=True)
    print(f"[end ] total spent ${global_spent():.2f}", flush=True)


if __name__ == "__main__":
    main()
