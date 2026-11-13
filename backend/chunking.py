"""Structure-aware chunking: one chunk per numbered section, with clause → page metadata.

Policies and regulations are written as numbered sections ("7. Breach Notification") and
clauses ("7.2 Notices to authorities ..."), and clauses often run across a page break.
Chunking by section keeps a clause whole, lets citations name "§7.2, p.1", and gives
keyword search the heading words.

Documents without at least MIN_HEADINGS increasing section headings fall back to plain
character splitting per page, so unstructured PDFs still work.
"""

import re
from dataclasses import dataclass, field

from langchain_text_splitters import RecursiveCharacterTextSplitter

from backend.pdf import Page

CHUNKER_VERSION = 2  # bump to re-index stored documents when chunking changes
MIN_HEADINGS = 3

_HEADING = re.compile(r"^(\d{1,2})\.\s+([A-Z][^\n]{1,80})$")
_CLAUSE = re.compile(r"^(\d{1,2})\.(\d{1,2})\s+\S")


@dataclass
class Chunk:
    text: str  # what is stored and shown as the passage
    search_text: str  # what is embedded and keyword-indexed: text plus document/section context
    metadata: dict = field(default_factory=dict)


@dataclass
class _Line:
    text: str
    page: int


@dataclass
class _Section:
    number: str | None
    heading: str | None
    lines: list[_Line] = field(default_factory=list)


def document_title(pages: list[Page], fallback: str) -> str:
    for page in pages:
        for line in page.text.splitlines():
            if line.strip():
                return line.strip()[:120]
    return fallback


def _lines(pages: list[Page]) -> list[_Line]:
    return [_Line(line.strip(), page.number) for page in pages for line in page.text.splitlines() if line.strip()]


def _sections(lines: list[_Line]) -> list[_Section]:
    """Split on headings whose numbers strictly increase (guards against numbered prose)."""
    sections = [_Section(None, None)]
    last = -1
    for line in lines:
        m = _HEADING.match(line.text)
        if m and int(m.group(1)) > last and not _CLAUSE.match(line.text):
            last = int(m.group(1))
            sections.append(_Section(m.group(1), m.group(2).strip(), [line]))
        else:
            sections[-1].lines.append(line)
    return [s for s in sections if s.lines]


def _join(lines: list[_Line]) -> str:
    """Re-join wrapped lines: clauses and headings start a new line, continuations don't."""
    out: list[str] = []
    for line in lines:
        if not out or _CLAUSE.match(line.text) or _HEADING.match(line.text):
            out.append(line.text)
        else:
            out[-1] = f"{out[-1]} {line.text}"
    return "\n".join(out)


def _clause_pages(section: _Section) -> dict[str, list[int]]:
    """Clause id → [first page, last page], following continuation lines across page breaks."""
    clauses: dict[str, list[int]] = {}
    current: str | None = None
    for line in section.lines:
        m = _CLAUSE.match(line.text)
        if m and m.group(1) == section.number:
            current = f"{m.group(1)}.{m.group(2)}"
            clauses[current] = [line.page, line.page]
        elif _HEADING.match(line.text):
            current = None
        elif current:
            clauses[current][1] = line.page
    return clauses


def _split_clauses(section: _Section, max_chars: int) -> list[list[_Line]]:
    """Split an over-long section at clause boundaries, keeping the heading with the first part."""
    groups: list[list[_Line]] = [[]]
    size = 0
    for line in section.lines:
        starts_clause = bool(_CLAUSE.match(line.text))
        if starts_clause and size > max_chars and groups[-1]:
            groups.append([])
            size = 0
        groups[-1].append(line)
        size += len(line.text) + 1
    return groups


def chunk_document(
    pages: list[Page], document_id: str, filename: str, chunk_size: int = 1000, chunk_overlap: int = 150
) -> list[Chunk]:
    title = document_title(pages, filename)
    base = {"document_id": document_id, "filename": filename}
    sections = _sections(_lines(pages))
    numbered = [s for s in sections if s.number is not None]

    if len(numbered) < MIN_HEADINGS:
        splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        return [
            Chunk(
                text=text,
                search_text=f"{title}\n{text}",
                metadata={**base, "page": page.number, "page_end": page.number},
            )
            for page in pages
            for text in splitter.split_text(page.text)
        ]

    chunks: list[Chunk] = []
    for section in sections:
        clauses = _clause_pages(section) if section.number else {}
        for group in _split_clauses(section, chunk_size):
            text = _join(group)
            if not text.strip():
                continue
            if section.number:
                context = f"{title} > {section.number}. {section.heading}"
                if group[0] is not section.lines[0]:  # continuation of a split section
                    text = f"{section.number}. {section.heading} (continued)\n{text}"
            else:
                context = title
            group_clauses = {c: p for c, p in clauses.items() if any(line.text.startswith(f"{c} ") for line in group)}
            chunks.append(
                Chunk(
                    text=text,
                    search_text=f"{context}\n{text}",
                    metadata={
                        **base,
                        "page": group[0].page,
                        "page_end": group[-1].page,
                        "section": section.number,
                        "heading": section.heading,
                        "clauses": group_clauses,
                    },
                )
            )
    return chunks
