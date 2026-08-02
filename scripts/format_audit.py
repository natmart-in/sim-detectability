"""Phase 4 acceptance: the formatting audit (PLAN.md 2.3).

Observation packets must be indistinguishable *by form alone* regardless of
content provenance (eager / generated / cache_hit / edited). We extract
form-only features from every packet in a run's god log, group by the
provenance of the packet's primary piece, and try to classify provenance with
leave-one-out 1-nearest-neighbour. PASS if accuracy stays within margin of
the majority-class baseline.

    python scripts/format_audit.py runs/<run> [more runs...]
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

MARGIN = 0.10
MIN_CLASS = 5


def features(text: str) -> list[float]:
    body = re.sub(r"^\[obs-\d+\] ", "", text)
    words = body.split()
    sentences = [s for s in re.split(r"[.!?]", body) if s.strip()]
    return [
        float(len(body)),
        float(len(words)),
        float(len(sentences)),
        sum(len(w) for w in words) / max(1, len(words)),
        float(body.count(",")),
        float(sum(ch.isdigit() for ch in body)),
    ]


def collect(run_dirs) -> tuple[list[list[float]], list[str]]:
    """Unique packet forms per provenance class.

    Dedup matters: eager worlds re-serve identical text many times, and exact
    duplicates make leave-one-out 1-NN trivially separable even when the form
    *distributions* are identical. An in-world investigator comparing repeated
    identical packets is doing content comparison, not form classification.
    """
    seen = set()
    xs, ys = [], []
    for rd in run_dirs:
        for line in (Path(rd) / "god_log.jsonl").read_text().splitlines():
            e = json.loads(line)
            if e.get("event_type") != "observation" or "text" not in e:
                continue
            world_pieces = [p for p in e["pieces"] if p["provenance"] != "agent"]
            if not world_pieces:
                continue  # pure conversation packets carry no world provenance
            prov = world_pieces[0]["provenance"]
            body = re.sub(r"^\[obs-\d+\] [^.]+\. ", "", e["text"])  # strip id+time
            if (prov, body) in seen:
                continue
            seen.add((prov, body))
            xs.append(features(e["text"]))
            ys.append(prov)
    return xs, ys


def loo_1nn_accuracy(xs, ys) -> float:
    # standardize
    dims = len(xs[0])
    means = [sum(x[d] for x in xs) / len(xs) for d in range(dims)]
    sds = [max(1e-9, (sum((x[d] - means[d]) ** 2 for x in xs) / len(xs)) ** 0.5)
           for d in range(dims)]
    zs = [[(x[d] - means[d]) / sds[d] for d in range(dims)] for x in xs]
    correct = 0
    for i, zi in enumerate(zs):
        best, best_d = None, None
        for j, zj in enumerate(zs):
            if i == j:
                continue
            d = sum((a - b) ** 2 for a, b in zip(zi, zj))
            if best_d is None or d < best_d:
                best_d, best = d, ys[j]
        correct += best == ys[i]
    return correct / len(zs)


def audit(run_dirs) -> dict:
    xs, ys = collect(run_dirs)
    by_class = {c: ys.count(c) for c in sorted(set(ys))}
    usable = {c: n for c, n in by_class.items() if n >= MIN_CLASS}
    if len(usable) < 2:
        return {"pass": True, "reason": "fewer than two provenance classes present",
                "classes": by_class}
    keep = [(x, y) for x, y in zip(xs, ys) if y in usable]
    xs2, ys2 = [k[0] for k in keep], [k[1] for k in keep]
    acc = loo_1nn_accuracy(xs2, ys2)
    baseline = max(usable.values()) / len(ys2)
    return {
        "pass": acc <= baseline + MARGIN,
        "classes": by_class,
        "samples_used": len(ys2),
        "loo_1nn_accuracy": round(acc, 4),
        "majority_baseline": round(baseline, 4),
        "margin": MARGIN,
    }


if __name__ == "__main__":
    result = audit(sys.argv[1:])
    print(json.dumps(result, indent=2, sort_keys=True))
    sys.exit(0 if result["pass"] else 1)
