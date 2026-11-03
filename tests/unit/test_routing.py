"""Tests for agentcore.routing and llm fallback / budget logic (OFFLINE=0 mocked)."""

from typing import Any
from unittest.mock import AsyncMock, patch

import litellm
import litellm.exceptions as litellm_exc
import pytest

import agentcore.offline as offline_mod
from agentcore.cost import RunCost
from agentcore.errors import BudgetExceeded
from agentcore.routing import Route, routes_for_tier


MESSAGES: list[dict[str, Any]] = [{"role": "user", "content": "hello"}]


@pytest.fixture()
def fixture_dir(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setattr(offline_mod, "FIXTURE_DIR", tmp_path)
    return tmp_path


@pytest.fixture()
def live_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OFFLINE", "0")


class TestRoutesForTier:
    def test_small_has_fallback(self) -> None:
        routes = routes_for_tier("small")
        assert len(routes) >= 2

    def test_unknown_tier_returns_default(self) -> None:
        routes = routes_for_tier("nonexistent")
        assert len(routes) >= 1
        assert all(isinstance(r, Route) for r in routes)


def _mock_response(content: str = "ok") -> Any:
    """Build a minimal litellm-shaped response object."""
    msg = type("Msg", (), {"content": content})()
    choice = type("Choice", (), {"message": msg})()
    usage = type("Usage", (), {"prompt_tokens": 3, "completion_tokens": 2})()
    return type("Resp", (), {"choices": [choice], "usage": usage})()


class TestFallback:
    async def test_429_on_first_route_falls_back(
        self, fixture_dir: Any, live_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """First route raises RateLimitError; second route succeeds."""
        from agentcore import llm as llm_mod

        good_response = _mock_response("fallback ok")
        call_count = 0

        async def fake_acompletion(model: str, **kwargs: Any) -> Any:
            nonlocal call_count
            call_count += 1
            # First model always 429s
            routes = routes_for_tier("small")
            if model == routes[0].model:
                raise litellm_exc.RateLimitError(
                    message="rate limit", llm_provider="test", model=model
                )
            return good_response

        monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
        monkeypatch.setattr(litellm, "completion_cost", lambda **_: 0.0)

        run_cost = RunCost()
        result = await llm_mod.complete(MESSAGES, run_cost=run_cost)
        assert result == "fallback ok"
        # First route was attempted (possibly retried), then second route succeeded
        assert call_count >= 2

    async def test_all_routes_fail_raises(
        self, fixture_dir: Any, live_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """All routes raise 503; expect RuntimeError."""
        from agentcore import llm as llm_mod

        async def always_fail(model: str, **kwargs: Any) -> Any:
            raise litellm_exc.ServiceUnavailableError(
                message="service unavailable",
                llm_provider="test",
                model=model,
            )

        monkeypatch.setattr(litellm, "acompletion", always_fail)

        with pytest.raises(RuntimeError, match="routes exhausted"):
            await llm_mod.complete(MESSAGES)


class TestBudget:
    async def test_budget_exceeded_before_call(
        self, fixture_dir: Any, live_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """RunCost already at limit → BudgetExceeded before any LLM call."""
        from agentcore import llm as llm_mod
        from resolute.config import settings

        called = False

        async def should_not_be_called(**kwargs: Any) -> Any:
            nonlocal called
            called = True
            return _mock_response()

        monkeypatch.setattr(litellm, "acompletion", should_not_be_called)

        from agentcore.cost import CallCost

        run_cost = RunCost()
        # Inject cost equal to the limit
        run_cost.record(
            CallCost(
                model="test",
                input_tokens=0,
                output_tokens=0,
                latency_ms=0,
                cost_usd=settings.budget_usd_max,
            )
        )

        with pytest.raises(BudgetExceeded):
            await llm_mod.complete(MESSAGES, run_cost=run_cost)

        assert not called
