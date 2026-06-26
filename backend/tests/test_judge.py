"""Tests for evals/judge.py — structured int judge via TestModel.

Overrides get_judge() with TestModel(custom_output_args=4) so no gateway
call is made and the result is deterministic.

Covers: evaluation-005
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
from pydantic_ai.models.test import TestModel

from evals.judge import get_judge, judge_text


@pytest.fixture(autouse=True)
def _clear_judge_cache() -> Generator[None, None, None]:
    """Clear get_judge lru_cache before and after each test.

    Ensures the judge agent is constructed fresh with the dummy key set by
    conftest._set_gateway_key, and that no stale agent bleeds between tests.
    """
    get_judge.cache_clear()
    yield
    get_judge.cache_clear()


async def test_judge_returns_custom_output() -> None:
    """TestModel(custom_output_args=4) → judge_text returns 4. (evaluation-005)

    Verifies that the structured int judge (output_type=int, temperature 0)
    can be overridden deterministically in CI/tests using TestModel, and that
    judge_text correctly returns the model's integer score.
    """
    with get_judge().override(model=TestModel(custom_output_args=4)):
        score = await judge_text("A philosophy lecture about stoicism and virtue.")
    assert score == 4


async def test_judge_score_in_valid_range() -> None:
    """judge_text always clamps the output to [1, 5]. (evaluation-005)"""
    with get_judge().override(model=TestModel(custom_output_args=4)):
        score = await judge_text("short text")
    assert 1 <= score <= 5
