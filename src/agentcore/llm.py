import time
from typing import Any

import litellm
from pydantic import BaseModel

from agentcore.cost import CallCost, RunCost
from agentcore.offline import is_offline, load_fixture, save_fixture
from resolute.config import settings

# Suppress litellm's default verbose logging
litellm.suppress_debug_info = True

_TIER_TO_MODEL: dict[str, str] = {
    "small": settings.model_small,
    "strong": settings.model_strong,
    "judge": settings.model_judge,
}

# Shared run-level cost accumulator; callers may replace with their own.
_default_run_cost = RunCost()


def get_default_run_cost() -> RunCost:
    return _default_run_cost


async def complete(
    messages: list[dict[str, Any]],
    *,
    schema: type[BaseModel] | None = None,
    model_tier: str = "small",
    run_cost: RunCost | None = None,
    **kwargs: Any,
) -> Any:
    """Call an LLM and return a parsed Pydantic model (if schema given) or raw text.

    With OFFLINE=1, replays a recorded fixture instead of calling the API.
    Records cost and latency into run_cost (falls back to the module-level default).
    """
    model = _TIER_TO_MODEL.get(model_tier, settings.model_small)
    schema_name = schema.__name__ if schema is not None else None
    tracker = run_cost if run_cost is not None else _default_run_cost

    if is_offline():
        raw = load_fixture(model_tier, messages, schema_name)
        content = raw.get("content", "")
        input_tokens = raw.get("input_tokens", 0)
        output_tokens = raw.get("output_tokens", 0)
        cost_usd = raw.get("cost_usd", 0.0)
        latency_ms = raw.get("latency_ms", 0.0)
        tracker.record(
            CallCost(
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
                cost_usd=cost_usd,
            )
        )
        if schema is not None:
            return schema.model_validate_json(content)
        return content

    # Live call via LiteLLM
    call_kwargs: dict[str, Any] = {"model": model, "messages": messages, **kwargs}
    if schema is not None:
        call_kwargs["response_format"] = schema

    t0 = time.perf_counter()
    response = await litellm.acompletion(**call_kwargs)
    latency_ms = (time.perf_counter() - t0) * 1000

    usage = getattr(response, "usage", None)
    input_tokens = getattr(usage, "prompt_tokens", 0) or 0
    output_tokens = getattr(usage, "completion_tokens", 0) or 0
    cost_usd = litellm.completion_cost(completion_response=response)

    live_content: str = response.choices[0].message.content or ""

    tracker.record(
        CallCost(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
        )
    )

    # Persist fixture for future offline replay
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

    if schema is not None:
        return schema.model_validate_json(live_content)
    return live_content
