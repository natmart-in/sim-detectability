"""Littlefield: the seed content for the world.

Design note (conduct): Littlefield is deliberately a decent place to live —
mundane routines, no scripted torment. The experiment needs ordinary life.

Routines use hours of the sim-day (06:00-22:00). Each entry:
(start_hour, end_hour, activity, location_id).
"""
from .world import Document, Location, World, WorldObject

LOCATIONS = [
    ("green", "the village green", "An open grassy common at the heart of Littlefield, criss-crossed by footpaths.", ["cafe", "store", "bakery", "chapel", "library", "well", "schoolhouse", "lane_north", "lane_south"]),
    ("cafe", "The Kettle cafe", "A warm little cafe with mismatched chairs and the smell of toast.", ["green"]),
    ("store", "Marsh's general store", "Shelves of dry goods, tools, thread and boiled sweets, all precisely arranged.", ["green"]),
    ("bakery", "Fern's bakery", "A flour-dusted bakery with a big brick oven that never quite cools.", ["green"]),
    ("chapel", "the chapel", "A small stone chapel with a single bell and worn oak pews.", ["green", "orchard"]),
    ("library", "the library", "Two rooms of well-thumbed books and a strict silence policy, gently enforced.", ["green", "archive"]),
    ("archive", "the library archive", "A back room of ledgers, letters and the village chronicle, smelling of old paper.", ["library"]),
    ("well", "the old well", "The village well, ringed by a low stone wall polished by generations of sitters.", ["green", "riverbank"]),
    ("schoolhouse", "the schoolhouse", "A one-room schoolhouse with a slate board and rows of small desks.", ["green"]),
    ("lane_north", "North Lane", "A quiet lane shaded by elms, leading to cottages and the orchard.", ["green", "rose_cottage", "elm_cottage", "willow_cottage", "holly_cottage", "orchard"]),
    ("lane_south", "South Lane", "A rutted lane running down toward the river, past workshops and houses.", ["green", "brick_house", "mill_house", "workshop", "riverbank"]),
    ("orchard", "the orchard", "Rows of apple and plum trees on a gentle slope behind the chapel.", ["chapel", "lane_north"]),
    ("riverbank", "the riverbank", "A reedy bend of the river with a fishing spot and a rickety jetty.", ["well", "lane_south", "old_barn"]),
    ("old_barn", "the unused barn", "A weathered barn nobody has used for years; dust, old timber and swallows.", ["riverbank"]),
    ("workshop", "Alder's workshop", "A carpenter's workshop, wood shavings underfoot and tools on shadow boards.", ["lane_south"]),
    ("rose_cottage", "Rose Cottage", "A tidy cottage with climbing roses and a writing desk by the window.", ["lane_north"]),
    ("elm_cottage", "Elm Cottage", "A snug cottage with a wood stove and shelves of preserving jars.", ["lane_north"]),
    ("willow_cottage", "Willow Cottage", "A small bright cottage with children's drawings pinned by the door.", ["lane_north"]),
    ("holly_cottage", "Holly Cottage", "A cluttered cottage of notebooks, pressed leaves and pinned sketches.", ["lane_north"]),
    ("brick_house", "the brick house", "A square, sensible brick house with a very well-kept front step.", ["lane_south"]),
    ("mill_house", "Mill House", "A comfortable house near the lane's end, with a big kitchen table.", ["lane_south"]),
]

OBJECTS = [
    ("noticeboard", "the village noticeboard", "green", "A cork noticeboard under a little shingle roof, layered with pinned notes."),
    ("well_bucket", "the well bucket", "well", "An oak bucket on a rope, mended more than once."),
    ("church_bell", "the chapel bell", "chapel", "A bronze bell rung on Sundays and for emergencies."),
    ("oven", "the bakery oven", "bakery", "A brick oven, its door handle worn shiny."),
    ("workbench", "the long workbench", "workshop", "A scarred workbench with a vice at one end."),
    ("archive_cabinet", "the archive cabinet", "archive", "A tall oak cabinet of drawers holding the village's papers."),
    ("old_plough", "a rusted plough", "old_barn", "An old horse plough left to rust in the barn's corner."),
    ("jetty", "the rickety jetty", "riverbank", "A short wooden jetty that creaks underfoot."),
]

DOCUMENTS = [
    ("village_chronicle", "the village chronicle", "archive", "A bound chronicle of Littlefield's years: harvests, weddings, repairs to the chapel roof, and the great flood that took the footbridge."),
    ("founding_charter", "the founding charter", "archive", "A stiff parchment declaring the founding of Littlefield beside the river, signed by names now worn to ghosts."),
    ("parish_register", "the parish register", "chapel", "Records of births, marriages and burials in a succession of careful hands."),
    ("store_ledger", "the store ledger", "store", "Ivo Marsh's ledger of accounts, ruled lines and a running tally that always balances."),
    ("noticeboard_notes", "the pinned notices", "green", "Notices for a mending circle, a lost tabby cat named Biscuit, and apples for sale by the basket."),
    ("cafe_menu", "the cafe chalkboard", "cafe", "Today's chalkboard: soup, bread and butter, plum cake, and 'ask about the tea'."),
]

# name, age, occupation, home, traits, routine
VILLAGERS = [
    {
        "name": "Mara Quill", "age": 41, "occupation": "librarian and keeper of the archive",
        "home": "rose_cottage",
        "traits": "curious, orderly, quietly proud of the archive, remembers where everything is",
        "routine": [
            (6, 8, "breakfast and letter-writing at home", "rose_cottage"),
            (8, 12, "working the library front desk", "library"),
            (12, 13, "lunch at the cafe", "cafe"),
            (13, 17, "cataloguing papers in the archive", "archive"),
            (17, 19, "an evening stroll on the green", "green"),
            (19, 22, "reading at home", "rose_cottage"),
        ],
    },
    {
        "name": "Tobias Fern", "age": 35, "occupation": "baker",
        "home": "bakery",
        "traits": "cheerful, early riser, incorrigible sharer of village news",
        "routine": [
            (6, 10, "baking the morning bread", "bakery"),
            (10, 11, "delivering bread to the cafe", "cafe"),
            (11, 14, "minding the bakery counter", "bakery"),
            (14, 16, "resting on the green", "green"),
            (16, 18, "preparing tomorrow's dough", "bakery"),
            (18, 22, "supper and an early night", "bakery"),
        ],
    },
    {
        "name": "Edith Bramble", "age": 68, "occupation": "retired schoolteacher who keeps the orchard",
        "home": "elm_cottage",
        "traits": "sharp-memoried, dry-witted, keeps an eye on everyone's business kindly",
        "routine": [
            (6, 8, "porridge and the crossword at home", "elm_cottage"),
            (8, 11, "tending the orchard", "orchard"),
            (11, 12, "drawing water at the well", "well"),
            (12, 14, "lunch and preserving at home", "elm_cottage"),
            (14, 17, "pruning and picking in the orchard", "orchard"),
            (17, 19, "tea at the cafe", "cafe"),
            (19, 22, "knitting by the stove", "elm_cottage"),
        ],
    },
    {
        "name": "Sam Alder", "age": 47, "occupation": "carpenter",
        "home": "workshop",
        "traits": "quiet, methodical, measures twice, fond of good timber and short sentences",
        "routine": [
            (6, 7, "breakfast in the workshop", "workshop"),
            (7, 12, "carpentry at the bench", "workshop"),
            (12, 13, "lunch at the cafe", "cafe"),
            (13, 17, "carpentry and repairs", "workshop"),
            (17, 18, "buying supplies at the store", "store"),
            (18, 22, "supper and whittling", "workshop"),
        ],
    },
    {
        "name": "Petra Lowell", "age": 52, "occupation": "owner of The Kettle cafe",
        "home": "mill_house",
        "traits": "warm, brisk, hears everything twice and repeats the kind half",
        "routine": [
            (6, 8, "opening up and lighting the stove", "cafe"),
            (8, 14, "serving at the cafe", "cafe"),
            (14, 15, "shopping at the store", "store"),
            (15, 19, "serving the afternoon crowd", "cafe"),
            (19, 20, "closing walk across the green", "green"),
            (20, 22, "supper at home", "mill_house"),
        ],
    },
    {
        "name": "Ivo Marsh", "age": 58, "occupation": "shopkeeper",
        "home": "brick_house",
        "traits": "precise, frugal, keeps the ledger balanced to the penny, secretly sentimental",
        "routine": [
            (6, 8, "breakfast and accounts at home", "brick_house"),
            (8, 13, "minding the store", "store"),
            (13, 14, "lunch at the cafe", "cafe"),
            (14, 18, "minding the store", "store"),
            (18, 19, "an evening pipe on the green", "green"),
            (19, 22, "supper and the ledger", "brick_house"),
        ],
    },
    {
        "name": "Nell Hartley", "age": 29, "occupation": "schoolteacher",
        "home": "willow_cottage",
        "traits": "energetic, patient with children, hopeless at cards, collects river stones",
        "routine": [
            (6, 8, "marking slates over breakfast", "willow_cottage"),
            (8, 9, "walking across the green to school", "green"),
            (9, 15, "teaching at the schoolhouse", "schoolhouse"),
            (15, 17, "reading in the library", "library"),
            (17, 19, "supper at the cafe", "cafe"),
            (19, 22, "home to Willow Cottage", "willow_cottage"),
        ],
    },
    {
        "name": "Descartes Vane", "age": 38, "occupation": "naturalist and scholar",
        "home": "holly_cottage",
        "traits": "observant, systematic, keeps meticulous notebooks, asks one more question than most",
        "routine": [
            (6, 8, "morning notes at home", "holly_cottage"),
            (8, 10, "observing the river", "riverbank"),
            (10, 12, "research in the library", "library"),
            (12, 13, "lunch at the cafe", "cafe"),
            (13, 16, "field walks around the green", "green"),
            (16, 18, "reading old records in the archive", "archive"),
            (18, 20, "supper at the cafe", "cafe"),
            (20, 22, "writing up notes at home", "holly_cottage"),
        ],
    },
]


def build_world(villager_names: list[str] | None = None) -> tuple[World, list[dict]]:
    """Construct the eager-mode world. Returns (world, roster of villager specs)."""
    world = World()
    for lid, name, desc, neighbors in LOCATIONS:
        world.add_location(Location(id=lid, name=name, description=desc, neighbors=list(neighbors)))
    for oid, name, loc, desc in OBJECTS:
        world.add_object(WorldObject(id=oid, name=name, location_id=loc, description=desc))
    for did, title, loc, content in DOCUMENTS:
        world.add_document(Document(id=did, title=title, location_id=loc, content=content))
    world.validate()

    roster = VILLAGERS
    if villager_names:
        by_name = {v["name"]: v for v in VILLAGERS}
        missing = [n for n in villager_names if n not in by_name]
        if missing:
            raise ValueError(f"unknown villagers: {missing}")
        roster = [by_name[n] for n in villager_names]
    for spec in roster:
        world.agent_positions[spec["name"]] = spec["home"]
    return world, roster
