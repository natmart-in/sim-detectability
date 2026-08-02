"""Append-only ground-truth log (simulator layer only — never visible in-world).

Every entry is canonical JSON (sorted keys, fixed separators) so that two
deterministic runs produce byte-identical logs. No wall-clock timestamps.
"""
import json
from pathlib import Path


def canonical(entry: dict) -> str:
    return json.dumps(entry, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class GodLog:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "w", encoding="utf-8")
        self.count = 0

    def append(self, tick: int, event_type: str, **fields):
        entry = {"seq": self.count, "tick": tick, "event_type": event_type, **fields}
        self._fh.write(canonical(entry) + "\n")
        self._fh.flush()
        self.count += 1

    def close(self):
        self._fh.close()

    @staticmethod
    def read(path: Path) -> list[dict]:
        with open(path, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]
