"""Phase 2 acceptance: an injected contradiction is caught; a clean run yields
zero leaks; legitimate world changes and agent-generated content don't count."""
from pathlib import Path

import yaml

from engine.clock import SimClock
from engine.engine import Runner
from engine.godlog import GodLog
from engine.littlefield import build_world
from engine.perception import Perception
from referee.leak_detector import detect

ROOT = Path(__file__).resolve().parents[1]


def _mini_world(tmp_path):
    world, _ = build_world(["Mara Quill", "Edith Bramble"])
    clock = SimClock()
    godlog = GodLog(tmp_path / "god_log.jsonl")
    return world, clock, godlog, Perception(world, clock, godlog)


def test_injected_contradiction_is_caught(tmp_path):
    world, clock, godlog, perc = _mini_world(tmp_path)
    world.agent_positions["Mara Quill"] = "archive"
    perc.read_document("Mara Quill", "village_chronicle")

    # Simulate an unlogged regeneration: the chronicle silently changes.
    clock.tick = 10
    world.documents["village_chronicle"].content = "A quite different history."
    perc.read_document("Mara Quill", "village_chronicle")
    godlog.close()

    report = detect(tmp_path)
    assert report["leaks_occurred"] == 1
    c = report["contradictions"][0]
    assert c["fact_key"] == "doc:village_chronicle:content"
    assert c["kind"] == "regeneration"
    # Mara saw both versions -> witnessed by a single agent
    assert report["leaks_witnessed"] == 1
    assert report["witnesses"][0]["single_witnesses"] == ["Mara Quill"]


def test_edit_between_sightings_is_classified_edit_stale(tmp_path):
    world, clock, godlog, perc = _mini_world(tmp_path)
    world.agent_positions["Mara Quill"] = "archive"
    perc.read_document("Mara Quill", "village_chronicle")

    clock.tick = 5
    godlog.append(5, "edit", fact_key="doc:village_chronicle:content",
                  mode="unpatched")
    world.documents["village_chronicle"].content = "An edited history."
    clock.tick = 12
    perc.read_document("Mara Quill", "village_chronicle")
    godlog.close()

    report = detect(tmp_path)
    assert report["leaks_occurred"] == 1
    assert report["contradictions"][0]["kind"] == "edit_stale"


def test_world_change_legitimises_new_content(tmp_path):
    world, clock, godlog, perc = _mini_world(tmp_path)
    world.agent_positions["Mara Quill"] = "green"
    perc.observe_location("Mara Quill")  # sees noticeboard_notes doc listed
    perc.read_document("Mara Quill", "noticeboard_notes")

    # An in-world causal change: someone pins a new notice (logged).
    clock.tick = 8
    godlog.append(8, "world_change", fact_key="doc:noticeboard_notes:content",
                  cause="agent pinned a new notice")
    world.documents["noticeboard_notes"].content = "New notice: barn dance on Sunday."
    clock.tick = 16
    perc.read_document("Mara Quill", "noticeboard_notes")
    godlog.close()

    report = detect(tmp_path)
    assert report["leaks_occurred"] == 0


def test_clean_runs_yield_zero_leaks(tmp_path):
    for cfg_name, patch in (("smoke.yaml", {}), ("phase1_mock.yaml", {"ticks": 96})):
        config = yaml.safe_load((ROOT / "configs" / cfg_name).read_text()) | patch
        out = tmp_path / cfg_name.split(".")[0]
        Runner(config, out).run()
        report = detect(out)
        assert report["leaks_occurred"] == 0, (cfg_name, report["contradictions"][:3])
        assert report["facts_scanned"] > 0
