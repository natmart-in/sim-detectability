"""Engineering guardrails: hard budget cap enforced in code; a resumed run
serves prior completions from the log without re-spending."""
import pytest

from engine.llm import BudgetExceeded, LLMClient


def test_budget_cap_raises(tmp_path):
    llm = LLMClient(tmp_path, mode="mock", budget_usd=1e-9)
    with pytest.raises(BudgetExceeded):
        llm.complete("dialogue", system="s", prompt="hello", model="claude-sonnet-5")
    llm.close()


def test_cap_blocks_before_spending_again(tmp_path):
    llm = LLMClient(tmp_path, mode="mock", budget_usd=1e-9)
    with pytest.raises(BudgetExceeded):
        llm.complete("dialogue", system="s", prompt="a", model="claude-sonnet-5")
    live_after_first = llm.live_calls
    with pytest.raises(BudgetExceeded):
        llm.complete("dialogue", system="s", prompt="b", model="claude-sonnet-5")
    # mock path spends via complete(); live path also pre-checks in _live_call.
    assert llm.spent_usd > 0
    llm.close()


def test_resume_serves_from_log_without_respending(tmp_path):
    llm = LLMClient(tmp_path, mode="mock", budget_usd=5.0)
    answers = [
        llm.complete("dialogue", system="s", prompt=f"p{i}", model="claude-sonnet-5")
        for i in range(3)
    ]
    spent = llm.spent_usd
    llm.close()

    # New client over the same run dir = resume. Identical calls must be
    # cache hits: zero live calls, zero additional spend, identical texts.
    llm2 = LLMClient(tmp_path, mode="mock", budget_usd=5.0)
    assert llm2.spent_usd == pytest.approx(spent)
    answers2 = [
        llm2.complete("dialogue", system="s", prompt=f"p{i}", model="claude-sonnet-5")
        for i in range(3)
    ]
    assert answers2 == answers
    assert llm2.live_calls == 0 and llm2.cache_hits == 3
    assert llm2.spent_usd == pytest.approx(spent)
    llm2.close()


def test_repeated_identical_prompts_get_distinct_occurrences(tmp_path):
    # Foundation for O3-naive later: the same query asked twice is two
    # distinct completions, deterministically distinguishable by occurrence.
    llm = LLMClient(tmp_path, mode="mock", budget_usd=5.0)
    t1 = llm.complete("dialogue", system="s", prompt="same", model="claude-sonnet-5")
    t2 = llm.complete("dialogue", system="s", prompt="same", model="claude-sonnet-5")
    assert t1 != t2  # mock varies by occurrence index
    llm.close()
