"""Structure-aware chunking: one chunk per numbered section, with clause → page metadata.

Policies and regulations are written as numbered sections ("7. Breach Notification") and
clauses ("7.2 Notices to authorities ...", "7.2.1 ..."), and clauses often run across a page
break. Chunking by section keeps a clause whole, lets citations name "§7.2, p.1", and gives
keyword search the heading words.

Guards against real-world PDFs:
- table-of-contents lines (dot leaders / trailing page numbers) are not headings;
- headings must continue the numbering (n == last+1 or last+2; the first may be up to 10),
  so a stray "99. Main St"
  doesn't swallow the document; a run of body-less headings (an unmarked contents list)
  is discarded when numbering restarts;
- a decimal at the start of a wrapped line ("2.5 percent ...") is only a clause when its
  first number is the current section's;
- header/footer lines repeated on most pages are dropped;
- sections without clause structure are still split to chunk_size.

Documents without at least MIN_HEADINGS headings fall back to plain splitting per page.
"""

import re
from collections import Counter
from dataclasses import dataclass, field

from langchain_text_splitters import RecursiveCharacterTextSplitter

from backend.pdf import Page

CHUNKER_VERSION = 3  # bump to re-index stored documents when chunking changes
MIN_HEADINGS = 3

_HEADING = re.compile(r"^(\d{1,2})\.\s+([A-Z][^\n]{1,80})$")
# Contents entries end in dot leaders or a wide gap before the page number ("Scope ..... 3").
_TOC_ENTRY = re.compile(r"(\.\s*){3,}\s*\d+$|(\s{2,}|\t)\d+$")
_CLAUSE = re.compile(r"^(\d{1,2}(?:\.\d{1,2})+)\.?\s+\S")


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
    lines = [_Line(line.strip(), page.number) for page in pages for line in page.text.splitlines() if line.strip()]
    if len(pages) < 3:
        return lines
    # Running headers/footers: the same short line on more than half of the pages.
    pages_with: Counter[str] = Counter()
    for page in pages:
        pages_with.update({line.strip() for line in page.text.splitlines() if line.strip()})
    repeated = {t for t, n in pages_with.items() if n > len(pages) / 2 and len(t) < 120}
    return [ln for ln in lines if ln.text not in repeated]


def _clause_id(line: str, section: str | None) -> str | None:
    """The clause id if this line starts a clause of `section` (e.g. "7.2" or "7.2.1")."""
    m = _CLAUSE.match(line)
    if m and section is not None and m.group(1).split(".")[0] == section:
        return m.group(1)
    return None


def _heading(line: str) -> tuple[int, str] | None:
    m = _HEADING.match(line)
    if not m or _CLAUSE.match(line) or _TOC_ENTRY.search(line):
        return None
    return int(m.group(1)), m.group(2).strip()


def _sections(lines: list[_Line]) -> list[_Section]:
    sections = [_Section(None, None)]
    last = -1
    for line in lines:
        found = _heading(line.text)
        if found:
            n, title = found
            numbered = [s for s in sections if s.number is not None]
            body_less = numbered and all(len(s.lines) == 1 for s in numbered)
            if n <= last and body_less and n <= 1:
                # The headings so far had no text under them: an unmarked contents list.
                front = sections[0]
                for s in numbered:
                    front.lines.extend(s.lines)
                sections, last = [front], -1
            if (last == -1 and n <= 10) or n in (last + 1, last + 2):
                last = n
                sections.append(_Section(str(n), title, [line]))
                continue
        sections[-1].lines.append(line)
    return [s for s in sections if s.lines]


def _join(lines: list[_Line], section: str | None) -> str:
    """Re-join wrapped lines: clauses and the heading start a new line, continuations don't."""
    out: list[str] = []
    for i, line in enumerate(lines):
        starts = i == 0 or _clause_id(line.text, section) is not None
        if not out or starts:
            out.append(line.text)
        else:
            out[-1] = f"{out[-1]} {line.text}"
    return "\n".join(out)


def _clause_pages(section: _Section) -> dict[str, list[int]]:
    """Clause id → [first page, last page], following continuation lines across page breaks."""
    clauses: dict[str, list[int]] = {}
    current: str | None = None
    for line in section.lines[1:]:
        if cid := _clause_id(line.text, section.number):
            current = cid
            clauses[current] = [line.page, line.page]
        elif current:
            clauses[current][1] = line.page
    return clauses


def _split_clauses(section: _Section, max_chars: int) -> list[list[_Line]]:
    """Split an over-long section at clause boundaries, keeping the heading with the first part."""
    groups: list[list[_Line]] = [[]]
    size = 0
    for line in section.lines:
        if _clause_id(line.text, section.number) and size + len(line.text) > max_chars and groups[-1]:
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
    splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    sections = _sections(_lines(pages))
    numbered = [s for s in sections if s.number is not None]

    if len(numbered) < MIN_HEADINGS:
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
        context = f"{title} > {section.number}. {section.heading}" if section.number else title
        for group in _split_clauses(section, chunk_size):
            text = _join(group, section.number)
            if not text.strip():
                continue
            if section.number and group[0] is not section.lines[0]:  # continuation of a split section
                text = f"{section.number}. {section.heading} (continued)\n{text}"
            group_clauses = {
                c: p for c, p in clauses.items() if any(_clause_id(ln.text, section.number) == c for ln in group)
            }
            # A section with no clause boundaries can still be huge: split it plainly.
            pieces = splitter.split_text(text) if len(text) > chunk_size * 1.5 else [text]
            for piece in pieces:
                if len(pieces) == 1:
                    piece_clauses = group_clauses
                else:
                    piece_clauses = {
                        c: p for c, p in group_clauses.items() if re.search(rf"(?m)^{re.escape(c)}\.?\s", piece)
                    }
                chunks.append(
                    Chunk(
                        text=piece,
                        search_text=f"{context}\n{piece}",
                        metadata={
                            **base,
                            "page": group[0].page,
                            "page_end": group[-1].page,
                            "section": section.number,
                            "heading": section.heading,
                            "clauses": piece_clauses,
                        },
                    )
                )
    return chunks
