#!/usr/bin/env python3
"""Collect docs + git history timestamps for the RAG corpus.

For each configured repo:
  1. Clones (or updates) the repo under /tmp/resolute_repos/<owner>_<name>.
  2. Walks all Markdown/RST/text files under docs/ and README.
  3. Looks up the first commit that added each file (first_seen_at).
  4. Writes one JSONL row per file to evals/data/corpus/<repo>.jsonl.

Schema: doc_id, repo, path, text, created_at

Usage:
    python scripts/collect_corpus.py           # uses DEFAULT_REPOS
    python scripts/collect_corpus.py --repos tiangolo/fastapi
"""
from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

ROOT = Path(__file__).parent.parent
CLONE_BASE = Path("/tmp/resolute_repos")

DEFAULT_REPOS: list[str] = [
    "tiangolo/fastapi",
    "pydantic/pydantic",
    "langchain-ai/langchain",
]
OUTPUT_DIR = ROOT / "evals" / "data" / "corpus"
DOC_EXTENSIONS = {".md", ".rst", ".txt"}
DOC_PATHS = {"docs", "doc", "documentation", "README.md", "README.rst"}


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class CorpusRow(BaseModel):
    doc_id: str
    repo: str
    path: str
    text: str
    created_at: str  # ISO-8601 — first git commit that introduced this file


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def _run(cmd: list[str], cwd: Path | None = None) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{result.stderr}")
    return result.stdout.strip()


def _clone_or_pull(repo: str) -> Path:
    owner, name = repo.split("/")
    dest = CLONE_BASE / f"{owner}_{name}"
    CLONE_BASE.mkdir(parents=True, exist_ok=True)
    if (dest / ".git").exists():
        print(f"  Pulling {repo}…")
        _run(["git", "pull", "--ff-only"], cwd=dest)
    else:
        print(f"  Cloning {repo}…")
        _run(["git", "clone", "--depth=500", f"https://github.com/{repo}.git", str(dest)])
    return dest


def _first_seen_at(repo_dir: Path, rel_path: str) -> str:
    """Return ISO-8601 timestamp of the commit that first added this file."""
    out = _run(
        ["git", "log", "--diff-filter=A", "--format=%aI", "--follow", "--", rel_path],
        cwd=repo_dir,
    )
    if not out:
        # Fall back to oldest available commit date
        out = _run(["git", "log", "--format=%aI", "--", rel_path], cwd=repo_dir)
    lines = [l for l in out.splitlines() if l.strip()]
    return lines[-1] if lines else datetime.now(UTC).isoformat()


def _doc_files(repo_dir: Path) -> list[Path]:
    """Return all documentation-ish files under the repo."""
    files: list[Path] = []
    for item in repo_dir.iterdir():
        if item.is_file() and item.suffix in DOC_EXTENSIONS:
            files.append(item)
    for doc_subdir in DOC_PATHS - {"README.md", "README.rst"}:
        sub = repo_dir / doc_subdir
        if sub.is_dir():
            for f in sub.rglob("*"):
                if f.is_file() and f.suffix in DOC_EXTENSIONS:
                    files.append(f)
    return files


async def collect_repo(repo: str) -> list[CorpusRow]:
    repo_dir = _clone_or_pull(repo)
    files = _doc_files(repo_dir)
    rows: list[CorpusRow] = []
    for f in files:
        rel = str(f.relative_to(repo_dir))
        try:
            text = f.read_text(errors="replace")
        except OSError:
            continue
        if not text.strip():
            continue
        created_at = _first_seen_at(repo_dir, rel)
        rows.append(
            CorpusRow(
                doc_id=f"{repo}::{rel}",
                repo=repo,
                path=rel,
                text=text[:50_000],  # cap at 50 kB per doc
                created_at=created_at,
            )
        )
    return rows


async def run(repos: list[str]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for repo in repos:
        safe = repo.replace("/", "_")
        out_path = OUTPUT_DIR / f"{safe}.jsonl"
        print(f"Collecting corpus for {repo}…")
        rows = await collect_repo(repo)
        with out_path.open("w") as fh:
            for row in rows:
                fh.write(row.model_dump_json() + "\n")
        print(f"  → {len(rows)} docs → {out_path}")

    print("Corpus collection complete.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repos",
        default=",".join(DEFAULT_REPOS),
        help="Comma-separated owner/repo list",
    )
    args = parser.parse_args()
    repos = [r.strip() for r in args.repos.split(",") if r.strip()]
    asyncio.run(run(repos))


if __name__ == "__main__":
    main()
