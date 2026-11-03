"""Chunk documents by Markdown heading hierarchy.

Strategy:
  - Walk the text top-to-bottom, tracking the current heading path.
  - Emit a chunk whenever the running token count exceeds MAX_TOKENS.
  - Each chunk carries its heading_path (breadcrumb) for context.
  - 50-token overlap: the last OVERLAP_TOKENS worth of characters from the
    previous chunk are prepended to the next one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ~400 tokens ≈ 1 600 characters (4 chars/token heuristic)
MAX_TOKENS: int = 400
OVERLAP_TOKENS: int = 50
CHARS_PER_TOKEN: int = 4

MAX_CHARS: int = MAX_TOKENS * CHARS_PER_TOKEN
OVERLAP_CHARS: int = OVERLAP_TOKENS * CHARS_PER_TOKEN

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


@dataclass
class Chunk:
    doc_id: str
    chunk_index: int
    heading_path: str  # e.g. "Introduction > Installation > Requirements"
    text: str
    # Metadata for the retrieval layer
    tenant_id: str = ""
    acl_roles: list[str] = field(default_factory=list)
    created_at: str = ""
    docs_version: str = ""

    def estimated_tokens(self) -> int:
        return max(1, len(self.text) // CHARS_PER_TOKEN)


def chunk_document(
    *,
    doc_id: str,
    text: str,
    tenant_id: str = "",
    acl_roles: list[str] | None = None,
    created_at: str = "",
    docs_version: str = "",
) -> list[Chunk]:
    """Split a Markdown document into heading-aware chunks with overlap."""
    if not text.strip():
        return []

    # Find all heading positions
    headings: list[tuple[int, int, str]] = []  # (start, level, title)
    for m in _HEADING_RE.finditer(text):
        level = len(m.group(1))
        title = m.group(2).strip()
        headings.append((m.start(), level, title))

    # Split text at heading boundaries → sections
    sections: list[tuple[str, str]] = []  # (heading_path, body)
    heading_stack: list[str] = []

    def _path() -> str:
        return " > ".join(heading_stack) if heading_stack else "Introduction"

    prev_end = 0

    for start, level, title in headings:
        # Flush text before this heading as part of current section
        pre_body = text[prev_end:start]
        if pre_body.strip():
            sections.append((_path(), pre_body))

        # Update heading stack
        # Pop headings of equal or deeper level
        while heading_stack and len(heading_stack) >= level:
            heading_stack.pop()
        heading_stack.append(title)
        prev_end = start

    # Flush remaining text
    tail = text[prev_end:]
    if tail.strip():
        sections.append((_path(), tail))

    # Build chunks from sections, flushing each section with its own heading path.
    # Overlap (last OVERLAP_CHARS of a chunk) is prepended to the next section's
    # buffer so adjacent chunks share context without crossing path boundaries.
    chunks: list[Chunk] = []
    chunk_idx = 0
    carry = ""  # overlap text carried from the previous emitted chunk

    def _emit(path: str, text: str) -> None:
        nonlocal chunk_idx
        chunks.append(
            Chunk(
                doc_id=doc_id,
                chunk_index=chunk_idx,
                heading_path=path,
                text=text,
                tenant_id=tenant_id,
                acl_roles=list(acl_roles or []),
                created_at=created_at,
                docs_version=docs_version,
            )
        )
        chunk_idx += 1

    for path, body in sections:
        buffer = carry + body
        while len(buffer) > MAX_CHARS:
            _emit(path, buffer[:MAX_CHARS])
            carry = buffer[MAX_CHARS - OVERLAP_CHARS : MAX_CHARS]
            buffer = carry + buffer[MAX_CHARS:]

        # buffer ≤ MAX_CHARS — flush it for this section now
        if buffer.strip():
            _emit(path, buffer)
            carry = buffer[-OVERLAP_CHARS:] if len(buffer) > OVERLAP_CHARS else buffer
        else:
            carry = ""

    return chunks
