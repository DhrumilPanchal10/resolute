"""Tests for agentcore/telemetry.py — OTel span helpers.

All tests use InMemorySpanExporter (no network) and OFFLINE=1.
"""

from __future__ import annotations

import pytest

from agentcore.telemetry import (
    _reset_provider,
    configure_test_exporter,
    init_telemetry,
    span_agent,
    span_llm,
    span_retrieval_stage,
    span_tool,
)


@pytest.fixture(autouse=True)
def _fresh_provider():
    """Give each test a clean tracer provider + in-memory exporter."""
    exporter = configure_test_exporter()
    yield exporter
    _reset_provider()


def _spans(exporter):
    return exporter.get_finished_spans()


# ---------------------------------------------------------------------------
# span_agent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_span_agent_creates_span(_fresh_provider):
    exporter = _fresh_provider
    async with span_agent("triage", tenant_id="t-1", ticket_id="tk-42"):
        pass
    spans = _spans(exporter)
    assert len(spans) == 1
    s = spans[0]
    assert s.name == "agent.triage"
    attrs = dict(s.attributes or {})
    assert attrs["resolute.node"] == "triage"
    assert attrs["resolute.tenant_id"] == "t-1"
    assert attrs["resolute.ticket_id"] == "tk-42"


@pytest.mark.asyncio
async def test_span_agent_records_exception(_fresh_provider):
    exporter = _fresh_provider
    with pytest.raises(ValueError, match="boom"):
        async with span_agent("resolver"):
            raise ValueError("boom")
    spans = _spans(exporter)
    assert len(spans) == 1
    s = spans[0]
    assert s.status.status_code.name == "ERROR"
    assert any(ev.name == "exception" for ev in s.events)


# ---------------------------------------------------------------------------
# span_llm
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_span_llm_attributes(_fresh_provider):
    exporter = _fresh_provider
    async with span_llm("gemini/gemini-1.5-flash", tier="small", tenant_id="t-1") as span:
        span.set_attribute("gen_ai.usage.input_tokens", 100)
        span.set_attribute("gen_ai.usage.output_tokens", 50)
        span.set_attribute("resolute.cost_usd", 0.001)
    spans = _spans(exporter)
    assert len(spans) == 1
    s = spans[0]
    assert s.name == "llm.complete"
    attrs = dict(s.attributes or {})
    assert attrs["gen_ai.request.model"] == "gemini/gemini-1.5-flash"
    assert attrs["resolute.tier"] == "small"
    assert attrs["resolute.tenant_id"] == "t-1"
    assert attrs["gen_ai.usage.input_tokens"] == 100
    assert attrs["gen_ai.usage.output_tokens"] == 50
    assert attrs["resolute.cost_usd"] == 0.001


# ---------------------------------------------------------------------------
# span_tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_span_tool_attributes(_fresh_provider):
    exporter = _fresh_provider
    async with span_tool("search_docs", tenant_id="t-2"):
        pass
    spans = _spans(exporter)
    assert len(spans) == 1
    s = spans[0]
    assert s.name == "tool.search_docs"
    attrs = dict(s.attributes or {})
    assert attrs["gen_ai.tool.name"] == "search_docs"
    assert attrs["resolute.tenant_id"] == "t-2"


@pytest.mark.asyncio
async def test_span_tool_custom_attributes(_fresh_provider):
    exporter = _fresh_provider
    async with span_tool("get_account", tenant_id="t-1", attributes={"account.id": "a-99"}):
        pass
    spans = _spans(exporter)
    s = spans[0]
    attrs = dict(s.attributes or {})
    assert attrs["account.id"] == "a-99"


# ---------------------------------------------------------------------------
# span_retrieval_stage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_span_retrieval_stage(_fresh_provider):
    exporter = _fresh_provider
    async with span_retrieval_stage("rerank", tenant_id="t-1", attributes={"k": 5}):
        pass
    spans = _spans(exporter)
    assert len(spans) == 1
    s = spans[0]
    assert s.name == "retrieval.rerank"
    attrs = dict(s.attributes or {})
    assert attrs["resolute.retrieval_stage"] == "rerank"
    assert attrs["resolute.tenant_id"] == "t-1"
    assert attrs["k"] == 5


# ---------------------------------------------------------------------------
# Nesting
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_nested_spans(_fresh_provider):
    exporter = _fresh_provider
    async with span_agent("triage", tenant_id="t-1"):
        async with span_llm("gemini/gemini-1.5-flash", tier="small"):
            pass
    spans = _spans(exporter)
    assert len(spans) == 2
    names = {s.name for s in spans}
    assert names == {"agent.triage", "llm.complete"}
    # LLM span should be a child of the agent span
    agent_span = next(s for s in spans if s.name == "agent.triage")
    llm_span = next(s for s in spans if s.name == "llm.complete")
    assert llm_span.parent is not None
    assert llm_span.parent.span_id == agent_span.context.span_id


# ---------------------------------------------------------------------------
# init_telemetry idempotency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_init_telemetry_idempotent(_fresh_provider):
    """Calling init_telemetry() twice doesn't crash or double-export."""
    exporter = _fresh_provider
    init_telemetry()
    init_telemetry()
    async with span_agent("test"):
        pass
    spans = _spans(exporter)
    assert len(spans) == 1
