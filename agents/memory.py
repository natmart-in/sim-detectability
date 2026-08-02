"""Memory stream + retrieval scored by recency, importance and relevance.

Kept deliberately small (PLAN.md 2.1). Relevance is token-overlap; importance
is a heuristic by memory kind (an LLM scorer can be slotted in later if the
heuristic proves too blunt). Persistence is one JSONL file per agent so the
referee can audit memories offline.
"""
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "at", "in", "on", "to", "you", "your",
    "is", "are", "was", "were", "i", "it", "with", "for", "here", "also", "no",
    "one", "else", "day", "am", "pm", "my", "me", "we", "our", "this", "that",
    "about", "what", "did", "do", "he", "she", "they",
}

IMPORTANCE_BY_KIND = {
    "observation": 2.0,
    "arrival": 2.0,
    "activity": 3.0,
    "document": 4.0,
    "dialogue": 5.0,
    "plan": 4.0,
    "reflection": 7.0,
}


def tokenize(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z']+", text.lower()) if w not in STOPWORDS}


@dataclass
class MemoryEntry:
    id: int
    tick: int
    kind: str
    text: str
    importance: float
    obs_ids: list[str] = field(default_factory=list)
    participants: list[str] = field(default_factory=list)


class MemoryStream:
    def __init__(self, agent: str, path: Path,
                 weights: dict | None = None, decay: float = 0.995):
        self.agent = agent
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.entries: list[MemoryEntry] = []
        self.weights = weights or {"recency": 0.6, "relevance": 1.0, "importance": 0.7}
        self.decay = decay
        self._fh = open(self.path, "w", encoding="utf-8")

    @classmethod
    def load(cls, agent: str, path: Path,
             weights: dict | None = None, decay: float = 0.995) -> "MemoryStream":
        """Read-only view of a persisted memory file (never truncates)."""
        self = object.__new__(cls)
        self.agent = agent
        self.path = Path(path)
        self.weights = weights or {"recency": 0.6, "relevance": 1.0, "importance": 0.7}
        self.decay = decay
        self._fh = None
        self.entries = []
        with open(self.path, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    self.entries.append(MemoryEntry(**json.loads(line)))
        return self

    def add(self, tick: int, kind: str, text: str,
            importance: float | None = None,
            obs_ids: list[str] | None = None,
            participants: list[str] | None = None) -> MemoryEntry:
        entry = MemoryEntry(
            id=len(self.entries), tick=tick, kind=kind, text=text,
            importance=importance if importance is not None else IMPORTANCE_BY_KIND.get(kind, 2.0),
            obs_ids=obs_ids or [], participants=participants or [],
        )
        self.entries.append(entry)
        self._fh.write(json.dumps(asdict(entry), sort_keys=True, ensure_ascii=False) + "\n")
        self._fh.flush()
        return entry

    def rewrite(self, entry_id: int, new_text: str):
        """Simulator-side memory edit (O4 patched sweep). Rewrites the file."""
        entry = self.entries[entry_id]
        assert entry.id == entry_id
        entry.text = new_text
        if self._fh:
            self._fh.close()
        self._fh = open(self.path, "w", encoding="utf-8")
        for e in self.entries:
            self._fh.write(json.dumps(asdict(e), sort_keys=True, ensure_ascii=False) + "\n")
        self._fh.flush()

    def score(self, entry: MemoryEntry, query_tokens: set[str], now_tick: int) -> float:
        recency = self.decay ** max(0, now_tick - entry.tick)
        etokens = tokenize(entry.text) | {p.lower() for p in entry.participants}
        overlap = len(query_tokens & etokens)
        relevance = overlap / (len(query_tokens) ** 0.5 + 1e-9) if query_tokens else 0.0
        w = self.weights
        return (w["recency"] * recency
                + w["relevance"] * min(relevance, 2.0)
                + w["importance"] * entry.importance / 10.0)

    def retrieve(self, query: str, now_tick: int, k: int = 6) -> list[MemoryEntry]:
        qt = tokenize(query)
        ranked = sorted(self.entries,
                        key=lambda e: (-self.score(e, qt, now_tick), e.id))
        return ranked[:k]

    def since(self, tick: int) -> list[MemoryEntry]:
        return [e for e in self.entries if e.tick >= tick]

    def recent(self, n: int) -> list[MemoryEntry]:
        return self.entries[-n:]

    def close(self):
        if self._fh:
            self._fh.close()
