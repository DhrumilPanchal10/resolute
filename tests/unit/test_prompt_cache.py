"""Tests for agentcore/prompt_cache.py."""
from __future__ import annotations

import pytest

from agentcore.prompt_cache import (
    CostTracker,
    NODE_TIER_MAP,
    build_cached_messages,
    estimate_prefix_tokens,
    prefix_hash,
    tier_for_node,
)


class TestBuildCachedMessages:
    def test_basic_structure(self) -> None:
        msgs = build_cached_messages("You are a bot.", "Hello")
        assert len(msgs) == 2
        assert msgs[0]["role"] == "system"
        assert msgs[0]["content"] == "You are a bot."
        assert msgs[1]["role"] == "user"
        assert msgs[1]["content"] == "Hello"

    def test_with_context_blocks(self) -> None:
        blocks = [
            {"role": "system", "content": "Tool: search_docs"},
            {"role": "system", "content": "Tool: get_account"},
        ]
        msgs = build_cached_messages("System.", "Query", context_blocks=blocks)
        assert len(msgs) == 4
        assert msgs[0]["content"] == "System."
        assert msgs[1]["content"] == "Tool: search_docs"
        assert msgs[2]["content"] == "Tool: get_account"
        assert msgs[3]["content"] == "Query"

    def test_system_prompt_first(self) -> None:
        """System prompt must be first for cache reuse."""
        msgs = build_cached_messages("Stable prefix.", "Variable content.")
        assert msgs[0]["role"] == "system"


class TestEstimatePrefixTokens:
    def test_basic_estimate(self) -> None:
        tokens = estimate_prefix_tokens("A" * 400)
        assert tokens == 100

    def test_with_context(self) -> None:
        blocks = [{"content": "B" * 200}]
        tokens = estimate_prefix_tokens("A" * 400, blocks)
        assert tokens == 150

    def test_empty(self) -> None:
        assert estimate_prefix_tokens("") == 0


class TestPrefixHash:
    def test_deterministic(self) -> None:
        h1 = prefix_hash("You are a triage bot.")
        h2 = prefix_hash("You are a triage bot.")
        assert h1 == h2
        assert len(h1) == 16

    def test_different_prompts_different_hash(self) -> None:
        h1 = prefix_hash("Prompt A")
        h2 = prefix_hash("Prompt B")
        assert h1 != h2


class TestTierForNode:
    def test_triage_uses_small(self) -> None:
        assert tier_for_node("triage") == "small"

    def test_knowledge_uses_small(self) -> None:
        assert tier_for_node("knowledge") == "small"

    def test_resolver_uses_strong(self) -> None:
        assert tier_for_node("resolver") == "strong"

    def test_investigator_uses_strong(self) -> None:
        assert tier_for_node("investigator") == "strong"

    def test_verifier_uses_small(self) -> None:
        assert tier_for_node("verifier") == "small"

    def test_unknown_node_defaults_small(self) -> None:
        assert tier_for_node("unknown_node") == "small"

    def test_override_upgrades(self) -> None:
        # Triage says "strong" for a critical ticket → resolver stays strong
        assert tier_for_node("triage", route_override="strong") == "strong"

    def test_override_does_not_downgrade(self) -> None:
        # Triage says "small" but resolver is normally "strong" → stays strong
        assert tier_for_node("resolver", route_override="small") == "strong"

    def test_all_nodes_in_map(self) -> None:
        expected = {"triage", "knowledge", "investigator", "resolver", "verifier"}
        assert set(NODE_TIER_MAP.keys()) == expected


class TestCostTracker:
    def test_empty_tracker(self) -> None:
        t = CostTracker(label="test")
        assert t.total_tickets == 0
        assert t.total_cost == 0.0
        assert t.avg_cost_per_ticket == 0.0

    def test_record_and_aggregate(self) -> None:
        t = CostTracker(label="before")
        t.record_call("t-1", "gpt-4", 100, 50, 0.01)
        t.record_call("t-1", "gpt-4", 200, 100, 0.02)
        t.record_call("t-2", "gpt-4", 150, 75, 0.015)
        assert t.total_tickets == 2
        assert t.total_cost == pytest.approx(0.045)
        assert t.avg_cost_per_ticket == pytest.approx(0.0225)
        assert t.total_tokens == 675

    def test_cached_tokens(self) -> None:
        t = CostTracker()
        t.record_call("t-1", "gpt-4", 100, 50, 0.005, cached_tokens=60)
        assert t.total_cached_tokens == 60
        assert t.cache_hit_ratio == pytest.approx(0.6)

    def test_compare(self) -> None:
        before = CostTracker(label="before")
        before.record_call("t-1", "gpt-4", 100, 50, 0.01)
        before.record_call("t-2", "gpt-4", 100, 50, 0.01)

        after = CostTracker(label="after")
        after.record_call("t-1", "gpt-4", 100, 50, 0.005, cached_tokens=50)
        after.record_call("t-2", "gpt-4", 100, 50, 0.005, cached_tokens=50)

        comp = before.compare(after)
        assert comp["before"]["avg_cost_per_ticket"] == pytest.approx(0.01)
        assert comp["after"]["avg_cost_per_ticket"] == pytest.approx(0.005)
        assert comp["cost_reduction"] == pytest.approx(0.5)
        assert comp["after"]["cache_hit_ratio"] == pytest.approx(0.5)
