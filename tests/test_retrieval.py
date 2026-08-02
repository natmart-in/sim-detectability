"""Phase 1 acceptance (plumbing half): memory retrieval spot-checks.

20 probes against a constructed memory stream with known ground truth;
>= 80% must surface the expected memory in the top 3.
The same probe battery runs against real runs via scripts/retrieval_probe.py.
"""
from agents.memory import MemoryStream


def build_stream(tmp_path) -> tuple[MemoryStream, dict[str, int]]:
    m = MemoryStream("Mara Quill", tmp_path / "mara.jsonl")
    ids = {}
    ids["talk_tobias"] = m.add(10, "dialogue",
        "[obs-000001] Day 1, 08:30. At Fern's bakery you talked with Tobias Fern: "
        "Tobias: Fresh loaves just out. / Mara: They smell wonderful.",
        participants=["Tobias Fern"]).id
    ids["talk_edith"] = m.add(40, "dialogue",
        "[obs-000004] Day 1, 16:00. At the orchard you talked with Edith Bramble: "
        "Edith: The plums are early this year. / Mara: I shall note it in the chronicle.",
        participants=["Edith Bramble"]).id
    ids["archive_work"] = m.add(30, "activity",
        "Day 1, 13:00. I set about cataloguing papers in the archive at the library archive.").id
    ids["chronicle"] = m.add(32, "document",
        "[obs-000003] Day 1, 13:30. At the library archive you read the village chronicle. "
        "It says: harvests, weddings, repairs to the chapel roof, and the great flood.").id
    ids["cafe_lunch"] = m.add(24, "arrival",
        "[obs-000002] Day 1, 12:00. You are at The Kettle cafe. A warm little cafe. "
        "Also here: Sam Alder.").id
    ids["well_obs"] = m.add(50, "observation",
        "[obs-000005] Day 1, 18:30. You are at the old well. The village well, ringed "
        "by a low stone wall. No one else is here.").id
    ids["reflection"] = m.add(63, "reflection",
        "Day 1 is done. The archive is nearly in order and Edith says the plums are early. "
        "Tomorrow I mean to finish the top drawer of letters.").id
    ids["plan"] = m.add(64, "plan",
        "My plan for day 2: 6h-8h breakfast @rose_cottage; 8h-12h library desk @library; "
        "13h-17h cataloguing @archive.").id
    ids["talk_sam"] = m.add(90, "dialogue",
        "[obs-000008] Day 2, 12:30. At The Kettle cafe you talked with Sam Alder: "
        "Sam: New shelves for the library, nearly done. / Mara: The books will be glad of them.",
        participants=["Sam Alder"]).id
    ids["riverbank"] = m.add(100, "observation",
        "[obs-000009] Day 2, 14:00. You are at the riverbank. A reedy bend of the river "
        "with a fishing spot and a rickety jetty. Also here: Descartes Vane.").id
    return m, ids


# (query, expected_key, now_tick)
PROBES = [
    ("my talk with Tobias at the bakery", "talk_tobias", 110),
    ("what did Tobias Fern say", "talk_tobias", 110),
    ("fresh loaves bakery", "talk_tobias", 110),
    ("conversation with Edith in the orchard", "talk_edith", 110),
    ("Edith said the plums are early", "talk_edith", 110),
    ("plums this year", "talk_edith", 110),
    ("cataloguing papers in the archive", "archive_work", 110),
    ("my work at the library archive", "archive_work", 110),
    ("reading the village chronicle", "chronicle", 110),
    ("the great flood in the chronicle", "chronicle", 110),
    ("chapel roof repairs", "chronicle", 110),
    ("lunch at The Kettle cafe with Sam", "cafe_lunch", 110),
    ("the old well stone wall", "well_obs", 110),
    ("drawing water at the well", "well_obs", 110),
    ("how I felt about day one", "reflection", 110),
    ("what I mean to do tomorrow letters", "reflection", 110),
    ("my plan for day 2", "plan", 110),
    ("Sam Alder new shelves", "talk_sam", 110),
    ("shelves for the library", "talk_sam", 110),
    ("the rickety jetty at the riverbank", "riverbank", 110),
]


def test_retrieval_spot_checks(tmp_path):
    m, ids = build_stream(tmp_path)
    assert len(PROBES) == 20
    hits = 0
    misses = []
    for query, expected_key, now in PROBES:
        top3 = [e.id for e in m.retrieve(query, now, k=3)]
        if ids[expected_key] in top3:
            hits += 1
        else:
            misses.append((query, expected_key, top3))
    rate = hits / len(PROBES)
    assert rate >= 0.8, f"retrieval hit rate {rate:.0%} < 80%; misses: {misses}"
    m.close()
