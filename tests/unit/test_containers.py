"""Tests for container configuration (Dockerfiles, docker-compose)."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


class TestDockerfiles:
    def test_api_dockerfile_exists(self) -> None:
        assert (ROOT / "Dockerfile.api").is_file()

    def test_worker_dockerfile_exists(self) -> None:
        assert (ROOT / "Dockerfile.worker").is_file()

    def test_api_multi_stage(self) -> None:
        text = (ROOT / "Dockerfile.api").read_text()
        assert text.count("FROM ") >= 2, "must be multi-stage"

    def test_worker_multi_stage(self) -> None:
        text = (ROOT / "Dockerfile.worker").read_text()
        assert text.count("FROM ") >= 2, "must be multi-stage"

    def test_api_non_root(self) -> None:
        text = (ROOT / "Dockerfile.api").read_text()
        assert "USER app" in text, "must run as non-root"

    def test_worker_non_root(self) -> None:
        text = (ROOT / "Dockerfile.worker").read_text()
        assert "USER app" in text, "must run as non-root"

    def test_api_exposes_8000(self) -> None:
        text = (ROOT / "Dockerfile.api").read_text()
        assert "EXPOSE 8000" in text

    def test_api_cmd_uvicorn(self) -> None:
        text = (ROOT / "Dockerfile.api").read_text()
        assert "uvicorn" in text

    def test_worker_cmd(self) -> None:
        text = (ROOT / "Dockerfile.worker").read_text()
        assert "resolute.worker" in text

    def test_dockerignore_exists(self) -> None:
        assert (ROOT / ".dockerignore").is_file()

    def test_dockerignore_excludes_env(self) -> None:
        text = (ROOT / ".dockerignore").read_text()
        assert ".env" in text


class TestDockerCompose:
    def _load(self) -> dict:
        return yaml.safe_load((ROOT / "docker-compose.yml").read_text())  # type: ignore[return-value]

    def test_api_service_present(self) -> None:
        cfg = self._load()
        assert "api" in cfg["services"]

    def test_worker_service_present(self) -> None:
        cfg = self._load()
        assert "worker" in cfg["services"]

    def test_api_depends_on_postgres(self) -> None:
        cfg = self._load()
        assert "postgres" in cfg["services"]["api"]["depends_on"]

    def test_api_depends_on_redis(self) -> None:
        cfg = self._load()
        assert "redis" in cfg["services"]["api"]["depends_on"]

    def test_api_port_mapping(self) -> None:
        cfg = self._load()
        assert "8000:8000" in cfg["services"]["api"]["ports"]

    def test_worker_memory_limit(self) -> None:
        cfg = self._load()
        limit = cfg["services"]["worker"]["deploy"]["resources"]["limits"]["memory"]
        assert limit is not None
