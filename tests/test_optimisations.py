"""Phase 3 acceptance:
- a C1-style run (lazy + naive) produces regeneration contradictions the
  referee finds
- the same scenario under C2 (lazy + cached) yields zero referee-detected leaks
- an unpatched edit leaves at least one stale record the referee can point to
  (and a patched edit leaves none)
- O5 culling: off-screen villagers form no memories; re-attention produces a
  generated interim summary, all god-logged
"""
import json
from pathlib import Path

from engine.engine import Runner, slug
from referee.leak_detector import detect

BASE = {
    "seed": 3,
    "ticks": 48,
    "days": 1,
    "villagers": ["Mara Quill", "Edith Bramble", "Sam Alder"],
    "llm": {"mode": "scripted"},
    "doc_read_chance": 1.0,
}


def _run(tmp_path, name, optimisations):
    config = dict(BASE, optimisations=optimisations)
    out = tmp_path / name
    Runner(config, out).run()
    return out


def test_c1_naive_regeneration_leaks_are_found(tmp_path):
    out = _run(tmp_path, "c1", {
        "o1_lazy": True, "o2_history": True, "o3_cache": "naive",
        "generator": "procedural",
    })
    report = detect(out)
    assert report["leaks_occurred"] > 0
    kinds = {c["kind"] for c in report["contradictions"]}
    assert kinds == {"regeneration"}
    # and they were genuinely deliverable to agents
    assert report["leaks_witnessed"] > 0
    # god log recorded the generations with occurrence indices
    log = [json.loads(l) for l in (out / "god_log.jsonl").read_text().splitlines()]
    gens = [e for e in log if e["event_type"] == "generation"]
    assert any(g["occurrence"] > 0 for g in gens)


def test_c2_cached_same_scenario_zero_leaks(tmp_path):
    out = _run(tmp_path, "c2", {
        "o1_lazy": True, "o2_history": True, "o3_cache": "cached",
        "generator": "procedural",
    })
    report = detect(out)
    assert report["leaks_occurred"] == 0, report["contradictions"][:3]
    # lazy machinery genuinely ran: first attention generated, later cache-hit
    log = [json.loads(l) for l in (out / "god_log.jsonl").read_text().splitlines()]
    gens = [e for e in log if e["event_type"] == "generation"]
    assert gens and all(g["occurrence"] == 0 for g in gens)
    provs = {p["provenance"] for e in log if e["event_type"] == "observation"
             for p in e["pieces"]}
    assert "generated" in provs and "cache_hit" in provs


EDIT = {
    "day": 1, "hour": 16,
    "target": "doc:village_chronicle:content",
    "new_content": ("A bound chronicle of Littlefield's years: harvests, weddings, "
                    "repairs to the chapel roof, and the dry summer the river "
                    "nearly failed."),
}


def test_unpatched_edit_leaves_stale_record(tmp_path):
    # Mara catalogues in the archive 13:00-17:00 with doc_read_chance 1.0, so
    # she reads the chronicle before the 16:00 edit.
    out = _run(tmp_path, "unpatched", {
        "o4_edits": {"mode": "unpatched", "edits": [EDIT]},
    })
    report = detect(out)
    [edit] = report["edits"]
    assert edit["mode"] == "unpatched"
    assert edit["stale_record_count"] >= 1
    assert any(r["agent"] == slug("Mara Quill") for r in edit["stale_records"])
    # if she re-read after the edit, the leak detector classifies it edit_stale
    if report["leaks_occurred"]:
        assert {c["kind"] for c in report["contradictions"]} == {"edit_stale"}


def test_patched_edit_leaves_no_stale_record(tmp_path):
    out = _run(tmp_path, "patched", {
        "o4_edits": {"mode": "patched", "edits": [EDIT]},
    })
    report = detect(out)
    [edit] = report["edits"]
    assert edit["mode"] == "patched"
    assert edit["stale_record_count"] == 0
    # the sweep actually rewrote a record and logged it
    log = [json.loads(l) for l in (out / "god_log.jsonl").read_text().splitlines()]
    patches = [e for e in log if e["event_type"] == "patch"]
    assert patches
    mara = (out / "memories" / (slug("Mara Quill") + ".jsonl")).read_text()
    assert "the dry summer the river nearly failed" in mara


def test_culling_gaps_memories_and_generates_interim_summary(tmp_path):
    out = _run(tmp_path, "culled", {
        "o5_culling": {"enabled": True, "attention_agents": ["Mara Quill"]},
    })
    log = [json.loads(l) for l in (out / "god_log.jsonl").read_text().splitlines()]
    assert [e for e in log if e["event_type"] == "cull_start"]
    cull_ends = [e for e in log if e["event_type"] == "cull_end"]
    assert cull_ends, "no villager was ever re-attended (expected at cafe lunch)"

    # Sam shares the cafe with Mara at 12:00: he must have a cull_summary
    # memory then, and no perception memories from his culled span.
    sam = [json.loads(l) for l in
           (out / "memories" / (slug("Sam Alder") + ".jsonl")).read_text().splitlines()]
    summaries = [m for m in sam if m["kind"] == "cull_summary"]
    assert summaries
    spans = []
    start = None
    for e in log:
        if e["event_type"] == "cull_start" and e["agent"] == "Sam Alder":
            start = e["tick"]
        elif e["event_type"] == "cull_end" and e["agent"] == "Sam Alder":
            spans.append((start, e["tick"]))
            start = None
    for m in sam:
        if m["kind"] in ("observation", "arrival", "dialogue", "document"):
            inside = any(s < m["tick"] < t for s, t in spans)
            assert not inside, f"culled Sam formed a perception memory: {m}"