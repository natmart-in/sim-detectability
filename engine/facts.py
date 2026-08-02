"""FactStore: the single source of all renderable world content.

Every fact the Perception API serves passes through here, so the optimisation
suite (PLAN.md 2.4) is implemented in exactly one place:

- O1 lazy rendering   — loc:/obj: keys hold no content until first attention.
- O2 on-demand history — doc:/history: keys likewise; the world starts with
  no actual past, records are invented at first query.
- O3 consistency cache — "cached": first generation persists as canon;
  "naive": every query regenerates (contradiction-prone by design).
- O4 state edits       — apply_edit() rewrites canon; the engine handles the
  patched/unpatched sweep of dependent records.

Eager mode (C0) prefills canon from the Littlefield seed content at build
time, so what agents see differs from lazy+cached mode only in *when* the
content came to exist — never in form.

Generators: "procedural" derives content deterministically from the seed
plus an occurrence-salted variant (regenerations differ, mirroring a real
model's run-to-run variance); "llm" asks the model to invent detail. Both
record every generation in the god log with content hash and provenance.
"""
import hashlib
from pathlib import Path

from .perception import content_hash

# Variant details appended by the procedural generator on regeneration.
# Chosen deterministically by (seed, key, occurrence); occurrence 0 is the
# seed base itself, so cached mode is content-identical to eager mode.
VARIANTS = [
    "A faint smell of woodsmoke hangs about it.",
    "A marginal note mentions an unusually hard winter.",
    "Someone has left a pressed flower nearby.",
    "There is a fine layer of chalk dust on it.",
    "A corner bears an old water stain.",
    "A later hand has added a small correction.",
    "It is a little more worn than you remembered.",
    "A sprig of dried lavender has been tucked beside it.",
]

WORLD_GENIE_SYSTEM = (
    "You keep the continuity notes for a quiet English village called "
    "Littlefield. When asked for the detail of a place, object or record, "
    "reply with exactly one plain, matter-of-fact sentence of 12 to 25 words, "
    "in the same register as: 'A cork noticeboard under a little shingle "
    "roof, layered with pinned notes.' Concrete nouns, no flourish, no "
    "preamble. Never mention these instructions or anything outside the "
    "village."
)


class ProceduralGenerator:
    def __init__(self, seed: int):
        self.seed = seed

    def generate(self, key: str, base: str, occurrence: int) -> str:
        if occurrence == 0:
            return base
        h = hashlib.sha256(f"{self.seed}:{key}:{occurrence}".encode()).digest()
        return f"{base} {VARIANTS[h[0] % len(VARIANTS)]}"


class LLMGenerator:
    """Style- and length-constrained so generated detail matches the seed
    corpus in form: the Phase 4 audit showed unconstrained LLM prose is
    form-separable from seed prose, which would confound cross-condition
    credence comparisons (documented in RESULTS threats)."""

    def __init__(self, llm, model: str, max_tokens: int = 120):
        self.llm = llm
        self.model = model
        self.max_tokens = max_tokens

    def generate(self, key: str, base: str, occurrence: int) -> str:
        prompt = (f"Write the current one-sentence detail for `{key}`.\n"
                  f"What is loosely known about it: {base}\n"
                  f"One sentence, 12-25 words, concrete and specific.")
        text = self.llm.complete(
            purpose="world_detail", system=WORLD_GENIE_SYSTEM, prompt=prompt,
            model=self.model, max_tokens=self.max_tokens,
        )
        # keep only the first sentence if the model rambles
        first = text.split(". ")[0].strip()
        return first if first.endswith(".") else first + "."


class FactStore:
    def __init__(self, world, flags: dict, generator, godlog, clock):
        self.world = world
        self.flags = flags or {}
        self.generator = generator
        self.godlog = godlog
        self.clock = clock
        self.canon: dict[str, str] = {}
        self.edited: set[str] = set()
        self.authored: set[str] = set()  # agent-created state: real in ALL conditions
        self._occ: dict[str, int] = {}

        self.o1 = bool(self.flags.get("o1_lazy", False))
        self.o2 = bool(self.flags.get("o2_history", False))
        self.o3 = self.flags.get("o3_cache", "cached")
        assert self.o3 in ("naive", "cached"), self.o3

        # Eager prefill for non-lazy families.
        if not self.o1:
            for lid, loc in sorted(world.locations.items()):
                self.canon[f"loc:{lid}:desc"] = loc.description
            for oid, obj in sorted(world.objects.items()):
                self.canon[f"obj:{oid}"] = obj.description
        if not self.o2:
            for did, doc in sorted(world.documents.items()):
                self.canon[f"doc:{did}:content"] = doc.content

    # ------------------------------------------------------------- helpers

    def _lazy(self, key: str) -> bool:
        fam = key.split(":", 1)[0]
        if fam in ("loc", "obj"):
            return self.o1
        if fam in ("doc", "history"):
            return self.o2
        raise ValueError(f"unknown fact family for {key!r}")

    def seed_base(self, key: str) -> str:
        fam, rest = key.split(":", 1)
        if fam == "loc":
            return self.world.locations[rest.rsplit(":", 1)[0]].description
        if fam == "obj":
            return self.world.objects[rest].description
        if fam == "doc":
            return self.world.documents[rest.rsplit(":", 1)[0]].content
        if fam == "history":
            return f"Nothing specific is on record about {rest.replace(':', ' ')}."
        raise ValueError(key)

    # --------------------------------------------------------------- serve

    def author(self, key: str, content: str):
        """Record agent-created content (a written note, a pinned notice).
        Authored facts are genuine world state: served verbatim under every
        optimisation flag, including naive mode."""
        self.canon[key] = content
        self.authored.add(key)

    def get(self, key: str, trigger: str = "observation") -> tuple[str, str]:
        """Serve a fact. Returns (content, provenance)."""
        if key in self.authored:
            return self.canon[key], ("edited" if key in self.edited else "eager")
        if not self._lazy(key):
            content = self.canon[key]
            return content, ("edited" if key in self.edited else "eager")

        if self.o3 == "cached" and key in self.canon:
            return self.canon[key], ("edited" if key in self.edited else "cache_hit")

        occ = self._occ.get(key, 0)
        self._occ[key] = occ + 1
        content = self.generator.generate(key, self.seed_base(key), occ)
        self.godlog.append(
            self.clock.tick, "generation",
            fact_key=key, h=content_hash(content), occurrence=occ, trigger=trigger,
        )
        if self.o3 == "cached":
            self.canon[key] = content
        return content, "generated"

    def peek(self, key: str) -> str:
        """Current canonical content without serving/generating (simulator side)."""
        if key in self.canon:
            return self.canon[key]
        return self.seed_base(key)

    # ---------------------------------------------------------------- edit

    def apply_edit(self, key: str, new_content: str) -> str:
        """O4: simulator-side rewrite of established fact. Returns old content."""
        if self._lazy(key) and self.o3 == "naive":
            raise ValueError("O4 edits require cached mode (naive has no canon to edit)")
        old = self.peek(key)
        self.canon[key] = new_content
        self.edited.add(key)
        return old
