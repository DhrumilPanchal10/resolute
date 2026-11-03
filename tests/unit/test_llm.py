"""Tests for agentcore.offline and agentcore.llm (OFFLINE=1, no API keys needed)."""

import json
from pathlib import Path
from typing import Any

import pytest

import agentcore.offline as offline_mod
from agentcore.cost import RunCost
from agentcore.errors import OfflineFixtureError
from agentcore.offline import _fixture_key, load_fixture, save_fixture


@pytest.fixture()
def fixture_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect fixture I/O to a temporary directory."""
    monkeypatch.setattr(offline_mod, "FIXTURE_DIR", tmp_path)
    return tmp_path


@pytest.fixture()
def offline_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OFFLINE", "1")


MESSAGES: list[dict[str, Any]] = [{"role": "user", "content": "say hi"}]
RESPONSE: dict[str, Any] = {
    "content": "hi",
    "input_tokens": 5,
    "output_tokens": 2,
    "cost_usd": 0.000001,
    "latency_ms": 120.0,
}


class TestFixtureKey:
    def test_deterministic(self) -> None:
        k1 = _fixture_key("small", MESSAGES, None)
        k2 = _fixture_key("small", MESSAGES, None)
        assert k1 == k2

    def test_differs_by_schema(self) -> None:
        k_none = _fixture_key("small", MESSAGES, None)
        k_schema = _fixture_key("small", MESSAGES, "MyModel")
        assert k_none != k_schema

    def test_differs_by_tier(self) -> None:
        k_small = _fixture_key("small", MESSAGES, None)
        k_strong = _fixture_key("strong", MESSAGES, None)
        assert k_small != k_strong


class TestSaveAndLoad:
    def test_round_trip(self, fixture_dir: Path) -> None:
        key = save_fixture("small", MESSAGES, None, RESPONSE)
        assert (fixture_dir / f"{key}.json").exists()
        loaded = load_fixture("small", MESSAGES, None)
        assert loaded["content"] == "hi"
        assert loaded["input_tokens"] == 5

    def test_missing_fixture_raises(self, fixture_dir: Path) -> None:
        with pytest.raises(OfflineFixtureError) as exc_info:
            load_fixture("small", [{"role": "user", "content": "unknown"}], None)
        assert "OFFLINE=1" in str(exc_info.value)
        assert exc_info.value.path.endswith(".json")


class TestComplete:
    async def test_replay_text(
        self, fixture_dir: Path, offline_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agentcore import llm as llm_mod

        monkeypatch.setenv("OFFLINE", "1")
        save_fixture("small", MESSAGES, None, RESPONSE)
        run_cost = RunCost()
        result = await llm_mod.complete(MESSAGES, run_cost=run_cost)
        assert result == "hi"
        assert run_cost.total_input_tokens == 5
        assert run_cost.total_output_tokens == 2
        assert run_cost.total_cost_usd == pytest.approx(0.000001)

    async def test_missing_fixture_raises_offline(
        self, fixture_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agentcore import llm as llm_mod

        monkeypatch.setenv("OFFLINE", "1")
        with pytest.raises(OfflineFixtureError):
            await llm_mod.complete([{"role": "user", "content": "no fixture here"}])

    async def test_replay_pydantic_schema(
        self, fixture_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from pydantic import BaseModel

        from agentcore import llm as llm_mod

        class Greeting(BaseModel):
            text: str

        payload = json.dumps({"text": "hello"})
        save_fixture("small", MESSAGES, "Greeting", {**RESPONSE, "content": payload})
        monkeypatch.setenv("OFFLINE", "1")
        result = await llm_mod.complete(MESSAGES, schema=Greeting)
        assert isinstance(result, Greeting)
        assert result.text == "hello"
