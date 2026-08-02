"""Deterministic per-stream RNGs derived from a single master seed.

Every source of randomness in the engine draws from a named stream so that
runs are exactly reproducible from (config, seed) alone.
"""
import random


class RngHub:
    def __init__(self, seed: int):
        self.seed = seed
        self._streams: dict[str, random.Random] = {}

    def stream(self, name: str) -> random.Random:
        if name not in self._streams:
            self._streams[name] = random.Random(f"{self.seed}:{name}")
        return self._streams[name]
