"""OpenTelemetry tracing for Resolute.

Tracer provider
---------------
Call `init_telemetry()` once at app startup.  It configures:
  - OTLP-HTTP exporter → `settings.otlp_endpoint` (Langfuse or Arize Phoenix).
  - Langfuse OTLP headers when `settings.langfuse_public_key` is set.
  - No-op exporter when `OFFLINE=1` or no endpoint is configured.

Span helpers
------------
All helpers are async context managers that accept an optional
`attributes` dict for extra key/value pairs.

  span_agent(name, tenant_id, ticket_id)   — wraps a LangGraph node
  span_llm(model, tier, tenant_id)         — wraps a single LLM call
  span_tool(tool_name, tenant_id)          — wraps an MCP tool call
  span_retrieval_stage(stage, tenant_id)   — wraps retrieval pipeline stages

Attribute naming follows the OpenTelemetry GenAI semantic conventions:
  gen_ai.request.model, gen_ai.usage.input_tokens, gen_ai.usage.output_tokens,
  gen_ai.tool.name
plus custom:
  resolute.cost_usd, resolute.tenant_id, resolute.ticket_id, resolute.tier
"""

from __future__ import annotations

import base64
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import NonRecordingSpan, Span, StatusCode

from agentcore.offline import is_offline

logger = logging.getLogger(__name__)

_TRACER_NAME = "resolute"

# Module-level provider — used by _tracer(). Avoids fighting OTel's global
# set-once semantics while still allowing test resets.
_provider: TracerProvider | None = None


def init_telemetry(
    *,
    endpoint: str = "",
    langfuse_public: str = "",
    langfuse_secret: str = "",
) -> None:
    """Initialise the module-level OTel tracer provider.

    Safe to call multiple times — subsequent calls are no-ops.
    In OFFLINE mode or when no endpoint is configured, spans are still
    recorded locally (via the provider) but not exported.
    """
    global _provider
    if _provider is not None:
        return

    resource = Resource.create({SERVICE_NAME: "resolute"})
    provider = TracerProvider(resource=resource)

    if not is_offline() and endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            headers: dict[str, str] = {}
            if langfuse_public and langfuse_secret:
                token = base64.b64encode(
                    f"{langfuse_public}:{langfuse_secret}".encode()
                ).decode()
                headers["Authorization"] = f"Basic {token}"

            exporter = OTLPSpanExporter(endpoint=endpoint, headers=headers)
            provider.add_span_processor(BatchSpanProcessor(exporter))
            logger.info("OTel → OTLP exporter at %s", endpoint)
        except Exception:
            logger.warning("Failed to create OTLP exporter; spans will be local only", exc_info=True)
    else:
        logger.debug("OTel: local-only mode (offline=%s, endpoint=%r)", is_offline(), endpoint)

    _provider = provider


def configure_test_exporter() -> InMemorySpanExporter:
    """Create a fresh TracerProvider with InMemorySpanExporter for tests.

    Returns the exporter so tests can call `.get_finished_spans()`.
    """
    global _provider
    exporter = InMemorySpanExporter()
    resource = Resource.create({SERVICE_NAME: "resolute-test"})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    _provider = provider
    return exporter


def _reset_provider() -> None:
    """Clear the module-level provider (test teardown)."""
    global _provider
    if _provider is not None:
        _provider.shutdown()
    _provider = None


def _tracer() -> trace.Tracer:
    if _provider is not None:
        return _provider.get_tracer(_TRACER_NAME)
    return trace.get_tracer(_TRACER_NAME)


def _set_span_error(span: Span, exc: BaseException) -> None:
    span.set_status(StatusCode.ERROR, str(exc))
    span.record_exception(exc)


# ---------------------------------------------------------------------------
# Span helpers
# ---------------------------------------------------------------------------


@asynccontextmanager
async def span_agent(
    node_name: str,
    *,
    tenant_id: str = "",
    ticket_id: str = "",
    attributes: dict[str, Any] | None = None,
) -> AsyncGenerator[Span, None]:
    """Async context manager that wraps a LangGraph agent node in an OTel span."""
    with _tracer().start_as_current_span(
        f"agent.{node_name}",
        kind=trace.SpanKind.INTERNAL,
    ) as span:
        if not isinstance(span, NonRecordingSpan):
            span.set_attribute("resolute.node", node_name)
            if tenant_id:
                span.set_attribute("resolute.tenant_id", tenant_id)
            if ticket_id:
                span.set_attribute("resolute.ticket_id", ticket_id)
            if attributes:
                for k, v in attributes.items():
                    span.set_attribute(k, v)
        try:
            yield span
        except Exception as exc:
            if not isinstance(span, NonRecordingSpan):
                _set_span_error(span, exc)
            raise


@asynccontextmanager
async def span_llm(
    model: str,
    *,
    tier: str = "",
    tenant_id: str = "",
    attributes: dict[str, Any] | None = None,
) -> AsyncGenerator[Span, None]:
    """Async context manager that wraps a single LLM call."""
    with _tracer().start_as_current_span(
        "llm.complete",
        kind=trace.SpanKind.CLIENT,
    ) as span:
        if not isinstance(span, NonRecordingSpan):
            span.set_attribute("gen_ai.request.model", model)
            if tier:
                span.set_attribute("resolute.tier", tier)
            if tenant_id:
                span.set_attribute("resolute.tenant_id", tenant_id)
        try:
            yield span
        except Exception as exc:
            if not isinstance(span, NonRecordingSpan):
                _set_span_error(span, exc)
            raise


@asynccontextmanager
async def span_tool(
    tool_name: str,
    *,
    tenant_id: str = "",
    attributes: dict[str, Any] | None = None,
) -> AsyncGenerator[Span, None]:
    """Async context manager that wraps an MCP tool call."""
    with _tracer().start_as_current_span(
        f"tool.{tool_name}",
        kind=trace.SpanKind.CLIENT,
    ) as span:
        if not isinstance(span, NonRecordingSpan):
            span.set_attribute("gen_ai.tool.name", tool_name)
            if tenant_id:
                span.set_attribute("resolute.tenant_id", tenant_id)
            if attributes:
                for k, v in attributes.items():
                    span.set_attribute(k, v)
        try:
            yield span
        except Exception as exc:
            if not isinstance(span, NonRecordingSpan):
                _set_span_error(span, exc)
            raise


@asynccontextmanager
async def span_retrieval_stage(
    stage: str,
    *,
    tenant_id: str = "",
    attributes: dict[str, Any] | None = None,
) -> AsyncGenerator[Span, None]:
    """Async context manager that wraps one stage of the retrieval pipeline."""
    with _tracer().start_as_current_span(
        f"retrieval.{stage}",
        kind=trace.SpanKind.INTERNAL,
    ) as span:
        if not isinstance(span, NonRecordingSpan):
            span.set_attribute("resolute.retrieval_stage", stage)
            if tenant_id:
                span.set_attribute("resolute.tenant_id", tenant_id)
            if attributes:
                for k, v in attributes.items():
                    span.set_attribute(k, v)
        try:
            yield span
        except Exception as exc:
            if not isinstance(span, NonRecordingSpan):
                _set_span_error(span, exc)
            raise
