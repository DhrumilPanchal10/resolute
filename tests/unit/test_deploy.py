"""Tests for deploy configuration files."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


class TestTerraform:
    TF = ROOT / "infra" / "terraform"

    def test_main_tf_exists(self) -> None:
        assert (self.TF / "main.tf").is_file()

    def test_variables_tf_exists(self) -> None:
        assert (self.TF / "variables.tf").is_file()

    def test_outputs_tf_exists(self) -> None:
        assert (self.TF / "outputs.tf").is_file()

    def test_main_has_ecs_cluster(self) -> None:
        text = (self.TF / "main.tf").read_text()
        assert "aws_ecs_cluster" in text

    def test_main_has_ecr_repos(self) -> None:
        text = (self.TF / "main.tf").read_text()
        assert "aws_ecr_repository" in text

    def test_main_uses_fargate(self) -> None:
        text = (self.TF / "main.tf").read_text()
        assert "FARGATE" in text

    def test_variables_has_database_url(self) -> None:
        text = (self.TF / "variables.tf").read_text()
        assert "database_url" in text

    def test_variables_marks_sensitive(self) -> None:
        text = (self.TF / "variables.tf").read_text()
        assert "sensitive" in text


class TestRender:
    def test_render_yaml_exists(self) -> None:
        assert (ROOT / "render.yaml").is_file()

    def test_render_has_api_service(self) -> None:
        cfg = yaml.safe_load((ROOT / "render.yaml").read_text())
        names = [s["name"] for s in cfg["services"]]
        assert "resolute-api" in names

    def test_render_has_worker_service(self) -> None:
        cfg = yaml.safe_load((ROOT / "render.yaml").read_text())
        names = [s["name"] for s in cfg["services"]]
        assert "resolute-worker" in names

    def test_render_api_uses_docker(self) -> None:
        cfg = yaml.safe_load((ROOT / "render.yaml").read_text())
        api = [s for s in cfg["services"] if s["name"] == "resolute-api"][0]
        assert api["runtime"] == "docker"


class TestVercel:
    def test_vercel_json_exists(self) -> None:
        assert (ROOT / "apps" / "web" / "vercel.json").is_file()

    def test_vercel_json_valid(self) -> None:
        data = json.loads((ROOT / "apps" / "web" / "vercel.json").read_text())
        assert data["framework"] == "nextjs"
