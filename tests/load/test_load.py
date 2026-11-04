"""Load test for the Resolute API (Python-based, no k6 required).

Runs concurrent requests against the FastAPI app using httpx + asyncio.
Works in OFFLINE=1 mode with canned LLM responses.

Measures:
  - p50/p95/p99 response times
  - Throughput (requests/second)
  - Error rate
  - Concurrent ticket processing
"""
from __future__ import annotations

import asyncio
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from agentcore.llm import _set_complete_fn
from agentcore.offline import is_offline
from resolute.graph.state import (
    ActionPlan,
    ResolverOutput,
    TriageResult,
    VerificationResult,
)


TICKET_TEXTS = [
    "I was charged twice for my Pro plan. Invoice INV-2024-001.",
    "Can't log in since the last deploy. Getting 401.",
    "How do I upgrade from Starter to Pro?",
    "Rate limit too low at 100 req/min. Need 500.",
    "CSV export button returns 500 error since yesterday.",
    "SSO with Okta stopped working this morning.",
    "Webhook delivery 10-15 minutes delayed.",
    "Password reset email not arriving.",
    "CORS errors on embedded widget.",
    "Feature flag enabled but old version showing.",
]


def _install_fake_complete() -> None:
    async def _fake(
        messages: list[dict[str, Any]], schema: Any = None, **_: Any,
    ) -> Any:
        if schema is TriageResult:
            return TriageResult(
                category="billing", severity="medium", tier="default",
                injection_risk=False, out_of_scope=False, summary="test",
            )
        if schema is ResolverOutput:
            return ResolverOutput(
                draft="We've resolved your issue.",
                evidence_ids=["ev-1"],
                action_plan=ActionPlan(actions=[]),
            )
        if schema is VerificationResult:
            return VerificationResult(verdict="pass", issues=[])
        system_msg = messages[0].get("content", "") if messages else ""
        if "knowledge retrieval" in system_msg:
            return '[{"source_id":"d-1","source_type":"docs","heading":"H","snippet":"S.","relevance":0.8}]'
        return '{"done": true, "findings": []}'

    _set_complete_fn(_fake)


# ---------------------------------------------------------------------------
# Direct graph load test (no HTTP server needed)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_tickets() -> None:
    """Process multiple tickets concurrently through the graph."""
    from resolute.graph.build import build_graph
    from resolute.graph.state import initial_state

    _install_fake_complete()
    try:
        graph = build_graph()
        latencies: list[float] = []
        errors: list[str] = []

        async def process_ticket(idx: int) -> None:
            text = TICKET_TEXTS[idx % len(TICKET_TEXTS)]
            ticket_id = f"load-{idx}"
            state = initial_state(
                ticket_id=ticket_id,
                tenant_id="tenant-load",
                user_id="user-load",
                ticket_text=text,
            )
            config = {"configurable": {"thread_id": ticket_id}}
            t0 = time.perf_counter()
            try:
                result = await graph.ainvoke(state, config=config)
                latency = (time.perf_counter() - t0) * 1000
                latencies.append(latency)
                assert result.get("final_reply") or result.get("draft")
            except Exception as exc:
                errors.append(str(exc))

        # Run 10 tickets concurrently
        tasks = [process_ticket(i) for i in range(10)]
        await asyncio.gather(*tasks)

        assert len(errors) == 0, f"Errors: {errors}"
        assert len(latencies) == 10

        p50 = statistics.median(latencies)
        p95 = sorted(latencies)[int(len(latencies) * 0.95)]
        p99 = sorted(latencies)[int(len(latencies) * 0.99)]

        print(f"\n{'=' * 50}")
        print(f"LOAD TEST RESULTS (10 concurrent tickets)")
        print(f"{'=' * 50}")
        print(f"p50: {p50:.0f} ms")
        print(f"p95: {p95:.0f} ms")
        print(f"p99: {p99:.0f} ms")
        print(f"Errors: {len(errors)}")

    finally:
        _set_complete_fn(None)


@pytest.mark.asyncio
async def test_sequential_throughput() -> None:
    """Measure throughput for sequential ticket processing."""
    from resolute.graph.build import build_graph
    from resolute.graph.state import initial_state

    _install_fake_complete()
    try:
        graph = build_graph()
        n = 5
        t0 = time.perf_counter()

        for i in range(n):
            text = TICKET_TEXTS[i % len(TICKET_TEXTS)]
            state = initial_state(
                ticket_id=f"seq-{i}",
                tenant_id="tenant-load",
                user_id="user-load",
                ticket_text=text,
            )
            config = {"configurable": {"thread_id": f"seq-{i}"}}
            result = await graph.ainvoke(state, config=config)
            assert isinstance(result, dict)

        elapsed = time.perf_counter() - t0
        throughput = n / elapsed

        print(f"\nSequential throughput: {throughput:.1f} tickets/sec ({n} tickets in {elapsed:.1f}s)")
        assert throughput > 0.5  # At least 0.5 tickets/sec in offline mode

    finally:
        _set_complete_fn(None)


@pytest.mark.asyncio
async def test_burst_load() -> None:
    """Burst of 20 simultaneous tickets."""
    from resolute.graph.build import build_graph
    from resolute.graph.state import initial_state

    _install_fake_complete()
    try:
        graph = build_graph()
        completed = 0
        errors = 0

        async def process(idx: int) -> bool:
            nonlocal completed, errors
            try:
                state = initial_state(
                    ticket_id=f"burst-{idx}",
                    tenant_id="tenant-load",
                    user_id="user-load",
                    ticket_text=TICKET_TEXTS[idx % len(TICKET_TEXTS)],
                )
                await graph.ainvoke(state, config={"configurable": {"thread_id": f"burst-{idx}"}})
                completed += 1
                return True
            except Exception:
                errors += 1
                return False

        t0 = time.perf_counter()
        tasks = [process(i) for i in range(20)]
        results = await asyncio.gather(*tasks)
        elapsed = time.perf_counter() - t0

        success_rate = sum(results) / len(results)

        print(f"\nBurst: {completed}/20 completed in {elapsed:.1f}s, {errors} errors")
        print(f"Success rate: {success_rate:.0%}")

        assert success_rate >= 0.9  # At least 90% success under burst

    finally:
        _set_complete_fn(None)
