"""Human-readable citation labels ("GDPR Sample Compliance §7.2, p.1").

Labels are built by the server from chunk metadata, never written by the model, so a
section number can't be invented. When a chunk holds several clauses, the clause whose
wording best overlaps the sentences that cite it is chosen; ties fall back to the section.
"""

import re
from pathlib import PurePath

from backend.hybrid import _tokens

_CLAUSE_LINE = re.compile(r"^(\d{1,2}\.\d{1,2})\s+(.*)$", re.MULTILINE)
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")


def document_name(filename: str) -> str:
    """'GDPR_Sample_Compliance.pdf' -> 'GDPR Sample Compliance'."""
    stem = PurePath(filename).stem
    return re.sub(r"[_\-]+", " ", stem).strip() or filename


def _pages(first: int, last: int | None) -> str:
    return f"p.{first}" if not last or last == first else f"pp.{first}–{last}"


def section_label(filename: str, page: int, page_end: int | None, section: str | None) -> str:
    name = document_name(filename)
    if section and section != "0":
        return f"{name} §{section}, {_pages(page, page_end)}"
    return f"{name}, {_pages(page, page_end)}"


def clause_label(filename: str, clause: str, pages: list[int]) -> str:
    return f"{document_name(filename)} §{clause}, {_pages(pages[0], pages[1])}"


def citing_sentences(answer: str, n: int) -> str:
    marker = re.compile(rf"\[(?:\d{{1,2}}\s*,\s*)*{n}(?:\s*,\s*\d{{1,2}})*\]")
    return " ".join(s for s in _SENTENCE.split(answer) if marker.search(s))


def best_clause(chunk_text: str, cited_text: str, clauses: dict) -> str | None:
    """The clause in this chunk that the citing sentence most clearly paraphrases, if any."""
    if not clauses or not cited_text:
        return None
    if len(clauses) == 1:
        return next(iter(clauses))
    wanted = set(_tokens([cited_text])[0])
    scored = sorted(
        (
            (len(wanted & set(_tokens([body])[0])), clause)
            for clause, body in _CLAUSE_LINE.findall(chunk_text)
            if clause in clauses
        ),
        reverse=True,
    )
    if not scored or scored[0][0] < 2 or (len(scored) > 1 and scored[0][0] == scored[1][0]):
        return None
    return scored[0][1]
