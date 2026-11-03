import hashlib
import json
import os
from pathlib import Path
from typing import Any

from agentcore.errors import OfflineFixtureError

# Overridable in tests via monkeypatch
FIXTURE_DIR: Path = Path(__file__).parent.parent.parent / "tests" / "fixtures" / "llm"


def _fixture_key(model_tier: str, messages: list[dict[str, Any]], schema_name: str | None) -> str:
    payload = json.dumps(
        {"model_tier": model_tier, "messages": messages, "schema": schema_name},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _fixture_path(key: str) -> Path:
    return FIXTURE_DIR / f"{key}.json"


def is_offline() -> bool:
    return os.environ.get("OFFLINE", "0") == "1"


def load_fixture(
    model_tier: str, messages: list[dict[str, Any]], schema_name: str | None
) -> dict[str, Any]:
    key = _fixture_key(model_tier, messages, schema_name)
    path = _fixture_path(key)
    if not path.exists():
        raise OfflineFixtureError(key=key, path=str(path))
    return json.loads(path.read_text())  # type: ignore[no-any-return]


def save_fixture(
    model_tier: str,
    messages: list[dict[str, Any]],
    schema_name: str | None,
    response: dict[str, Any],
) -> str:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    key = _fixture_key(model_tier, messages, schema_name)
    _fixture_path(key).write_text(json.dumps(response, indent=2))
    return key
