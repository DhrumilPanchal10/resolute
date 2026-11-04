import time
from collections.abc import Callable
from typing import Any

import litellm
import litellm.exceptions as litellm_exc
from pydantic import BaseModel
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from agentcore.cost import CallCost, RunCost
from agentcore.errors import BudgetExceeded
from agentcore.offline import is_offline, load_fixture, save_fixture
from agentcore.routing import Route, routes_for_tier
from agentcore.telemetry import span_llm
from resolute.config import settings

# ---------------------------------------------------------------------------
# Test / demo override hook
# ---------------------------------------------------------------------------

_complete_override: Callable[..., Any] | None = None


def _set_complete_fn(fn: Callable[..., Any] | None) -> None:
    """Inject a replacement for `complete()` — used in tests and the demo.

    When set, `complete()` delegates entirely to `fn(messages, schema, **kwargs)`
    and skips all routing, retries, budget checks, and fixture I/O.
    Call with `None` to restore normal behaviour.
    """
    global _complete_override
    _complete_override = fn


# Suppress litellm's default verbose logging
litellm.suppress_debug_info = True

_MAX_RETRIES_PER_ROUTE = 2
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
_RETRYABLE_TYPES = (
    litellm_exc.RateLimitError,
    litellm_exc.InternalServerError,
    litellm_exc.ServiceUnavailableError,
    litellm_exc.BadGatewayError,
    litellm_exc.APIConnectionError,
)


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, _RETRYABLE_TYPES)


def _make_retrying_call(route: Route) -> Any:
    """Return a tenacity-wrapped async callable for a single route."""

    @retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(_MAX_RETRIES_PER_ROUTE),
        wait=wait_exponential_jitter(multiplier=0.5, max=10),
        reraise=True,
    )
    async def _call(**kwargs: Any) -> Any:
        return await litellm.acompletion(model=route.model, **kwargs)

    return _call


async def complete(
    messages: list[dict[str, Any]],
    *,
    schema: type[BaseModel] | None = None,
    model_tier: str = "small",
    run_cost: RunCost | None = None,
    **kwargs: Any,
) -> Any:
    """Call an LLM and return a parsed Pydantic model (if schema given) or raw text.

    - OFFLINE=1: replays a recorded fixture; missing fixture raises OfflineFixtureError.
    - Live: iterates routes_for_tier(), retrying each with exponential back-off+jitter;
      falls back to the next route when retries for one route are exhausted.
    - Raises BudgetExceeded before any call that would exceed settings.budget_usd_max.
    - Auto-saves each live response as a fixture for future offline replay.
    """
    if _complete_override is not None:
        return await _complete_override(messages, schema=schema, model_tier=model_tier, **kwargs)

    tracker = run_cost if run_cost is not None else RunCost()
    schema_name = schema.__name__ if schema is not None else None

    # --- Budget pre-check ---
    if tracker.total_cost_usd >= settings.budget_usd_max:
        raise BudgetExceeded(spent=tracker.total_cost_usd, limit=settings.budget_usd_max)

    # --- Offline replay ---
    if is_offline():
        raw = load_fixture(model_tier, messages, schema_name)
        _record_cost(tracker, raw.get("model", model_tier), raw)
        return _parse(raw["content"], schema)

    # --- Live call with route fallback ---
    routes = routes_for_tier(model_tier)
    last_exc: BaseException | None = None

    for route in routes:
        call = _make_retrying_call(route)
        call_kwargs: dict[str, Any] = {"messages": messages, **kwargs}
        if schema is not None:
            call_kwargs["response_format"] = schema

        async with span_llm(route.model, tier=model_tier) as span:
            try:
                t0 = time.perf_counter()
                response = await call(**call_kwargs)
                latency_ms = (time.perf_counter() - t0) * 1000
            except _RETRYABLE_TYPES as exc:
                last_exc = exc
                continue  # try next route

            usage = getattr(response, "usage", None)
            input_tokens = getattr(usage, "prompt_tokens", 0) or 0
            output_tokens = getattr(usage, "completion_tokens", 0) or 0
            cost_usd = litellm.completion_cost(completion_response=response)
            live_content: str = response.choices[0].message.content or ""

            span.set_attribute("gen_ai.usage.input_tokens", input_tokens)
            span.set_attribute("gen_ai.usage.output_tokens", output_tokens)
            span.set_attribute("resolute.cost_usd", cost_usd)
            span.set_attribute("resolute.latency_ms", latency_ms)

            tracker.record(
                CallCost(
                    model=route.model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_ms=latency_ms,
                    cost_usd=cost_usd,
                )
            )

            save_fixture(
                model_tier,
                messages,
                schema_name,
                {
                    "content": live_content,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cost_usd": cost_usd,
                    "latency_ms": latency_ms,
                },
            )

            return _parse(live_content, schema)

    raise RuntimeError(f"All routes exhausted for tier={model_tier!r}.") from last_exc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _record_cost(tracker: RunCost, model: str, raw: dict[str, Any]) -> None:
    tracker.record(
        CallCost(
            model=model,
            input_tokens=raw.get("input_tokens", 0),
            output_tokens=raw.get("output_tokens", 0),
            latency_ms=raw.get("latency_ms", 0.0),
            cost_usd=raw.get("cost_usd", 0.0),
        )
    )


def _parse(content: str, schema: type[BaseModel] | None) -> Any:
    if schema is not None:
        return schema.model_validate_json(content)
    return content
