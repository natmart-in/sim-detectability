"""LLM access layer: single door for every completion in the system.

- Every completion is persisted to <run_dir>/llm_log.jsonl so any run can be
  replayed and audited from logs alone.
- Cache-first: if an identical call (same purpose/model/prompts, same
  occurrence index) exists in the log, it is returned without spending.
  Because the engine is deterministic, this gives resume-without-respending.
- A hard budget cap is enforced in code before every live call.
- Modes: "live" (Anthropic API), "mock" (deterministic canned outputs).

Note on model params: temperature/top_p/top_k are rejected by claude-sonnet-5 /
claude-opus-5 and are never sent. Behavioural steering is done via prompts and
the `effort` output config (PLAN.md's "temperature low/moderate" is realised
this way — documented deviation).
"""
import hashlib
import json
from pathlib import Path

# USD per million tokens. Standard (non-introductory) rates as of 2026-08;
# override in config if pricing changes. Metering at standard rates slightly
# overestimates cost during the sonnet-5 intro period — safe direction.
DEFAULT_PRICING = {
    "claude-sonnet-5": {"input": 3.00, "output": 15.00, "cache_read": 0.30, "cache_write": 3.75},
    "claude-opus-5": {"input": 5.00, "output": 25.00, "cache_read": 0.50, "cache_write": 6.25},
    "claude-fable-5": {"input": 10.00, "output": 50.00, "cache_read": 1.00, "cache_write": 12.50},
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00, "cache_read": 0.10, "cache_write": 1.25},
}


class BudgetExceeded(RuntimeError):
    pass


class LLMError(RuntimeError):
    pass


def _usage_cost(pricing: dict, model: str, usage: dict) -> float:
    if model not in pricing:
        raise LLMError(f"no pricing configured for model {model!r}")
    p = pricing[model]
    return (
        usage.get("input_tokens", 0) * p["input"]
        + usage.get("output_tokens", 0) * p["output"]
        + usage.get("cache_read_input_tokens", 0) * p["cache_read"]
        + usage.get("cache_creation_input_tokens", 0) * p["cache_write"]
    ) / 1_000_000


class LLMClient:
    def __init__(self, run_dir: Path, mode: str = "live",
                 pricing: dict | None = None, budget_usd: float = 5.0):
        assert mode in ("live", "mock"), mode
        self.mode = mode
        self.pricing = pricing or DEFAULT_PRICING
        self.budget_usd = budget_usd
        self.log_path = Path(run_dir) / "llm_log.jsonl"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        # cache: key -> list of entries in occurrence order
        self._cache: dict[str, list[dict]] = {}
        self._occurrence: dict[str, int] = {}
        self.spent_usd = 0.0
        self.calls = 0
        self.live_calls = 0
        self.cache_hits = 0
        self.tokens = {"input_tokens": 0, "output_tokens": 0,
                       "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        if self.log_path.exists():
            with open(self.log_path, encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        e = json.loads(line)
                        self._cache.setdefault(e["key"], []).append(e)
                        self.spent_usd += e["cost_usd"]
        self._fh = open(self.log_path, "a", encoding="utf-8")
        self._anthropic = None

    @staticmethod
    def call_key(purpose: str, model: str, system: str, prompt: str,
                 max_tokens: int, effort: str | None) -> str:
        blob = json.dumps([purpose, model, system, prompt, max_tokens, effort],
                          sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def complete(self, purpose: str, system: str, prompt: str, model: str,
                 max_tokens: int = 512, effort: str | None = None) -> str:
        key = self.call_key(purpose, model, system, prompt, max_tokens, effort)
        occ = self._occurrence.get(key, 0)
        self._occurrence[key] = occ + 1
        self.calls += 1

        cached = self._cache.get(key, [])
        if occ < len(cached):
            self.cache_hits += 1
            return cached[occ]["text"]

        if self.mode == "mock":
            text = self._mock_text(purpose, key, occ)
            usage = {"input_tokens": (len(system) + len(prompt)) // 4,
                     "output_tokens": len(text) // 4,
                     "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        else:
            text, usage = self._live_call(purpose, system, prompt, model, max_tokens, effort)

        cost = _usage_cost(self.pricing, model, usage)
        self.spent_usd += cost
        self.live_calls += 1
        for k in self.tokens:
            self.tokens[k] += usage.get(k, 0)
        entry = {"key": key, "occ": occ, "purpose": purpose, "model": model,
                 "system": system, "prompt": prompt, "text": text,
                 "usage": usage, "cost_usd": cost, "effort": effort,
                 "max_tokens": max_tokens}
        self._cache.setdefault(key, []).append(entry)
        self._fh.write(json.dumps(entry, sort_keys=True, ensure_ascii=False) + "\n")
        self._fh.flush()

        if self.spent_usd >= self.budget_usd:
            raise BudgetExceeded(
                f"budget cap hit: spent ${self.spent_usd:.4f} >= cap ${self.budget_usd:.2f}"
            )
        return text

    def _live_call(self, purpose, system, prompt, model, max_tokens, effort):
        # Enforce the cap *before* spending as well as after.
        if self.spent_usd >= self.budget_usd:
            raise BudgetExceeded(
                f"budget cap hit before call: ${self.spent_usd:.4f} >= ${self.budget_usd:.2f}"
            )
        if self._anthropic is None:
            import anthropic
            self._anthropic = anthropic.Anthropic()
        kwargs = dict(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        if effort:
            kwargs["output_config"] = {"effort": effort}
        resp = self._anthropic.messages.create(**kwargs)
        if resp.stop_reason == "refusal":
            raise LLMError(f"model refused a {purpose} completion")
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        usage = {
            "input_tokens": resp.usage.input_tokens,
            "output_tokens": resp.usage.output_tokens,
            "cache_read_input_tokens": getattr(resp.usage, "cache_read_input_tokens", 0) or 0,
            "cache_creation_input_tokens": getattr(resp.usage, "cache_creation_input_tokens", 0) or 0,
        }
        return text, usage

    @staticmethod
    def _mock_text(purpose: str, key: str, occ: int) -> str:
        """Deterministic stand-in output, keyed by call content and occurrence.

        Occurrence is part of the identity so that (in later phases) a
        naive-mode regeneration of the same query can yield a *different*
        deterministic answer — mirroring a real model's run-to-run variance.
        """
        tag = f"{key[:8]}:{occ}"
        if purpose == "daily_plan":
            # Sentinel: planner falls back to the villager's seed routine.
            return "MOCK_DEFAULT_PLAN"
        if purpose == "dialogue":
            return f"Mmh, quite so — though I'd say it depends on the weather. [mock {tag}]"
        if purpose == "reflection":
            return (f"Today was an ordinary day, and the ordinary days are the ones "
                    f"I trust most. [mock {tag}]")
        return f"[mock {purpose} {tag}]"

    def summary(self) -> dict:
        return {
            "mode": self.mode,
            "calls": self.calls,
            "live_calls": self.live_calls,
            "cache_hits": self.cache_hits,
            "tokens": dict(self.tokens),
            "spent_usd": round(self.spent_usd, 6),
            "budget_usd": self.budget_usd,
        }

    def close(self):
        self._fh.close()
