"""PDF text extraction, page by page, so answers can cite page numbers."""

import re
from dataclasses import dataclass

import pymupdf as fitz


class PDFError(ValueError):
    """The file can't be turned into searchable text. The message is shown to the user."""


@dataclass(frozen=True)
class Page:
    number: int  # 1-based
    text: str


_HYPHEN_BREAK = re.compile(r"(\w)-\n(\w)")
_SPACES = re.compile(r"[ \t ]+")
_BLANK_LINES = re.compile(r"\n{3,}")


def clean_text(text: str) -> str:
    text = _HYPHEN_BREAK.sub(r"\1\2", text)
    text = _SPACES.sub(" ", text)
    text = "\n".join(line.strip() for line in text.splitlines())
    return _BLANK_LINES.sub("\n\n", text).strip()


def extract_pages(data: bytes, max_pages: int = 1000) -> list[Page]:
    """Return the non-empty pages of a PDF. Raises PDFError with a user-facing reason."""
    if not data.startswith(b"%PDF-"):
        raise PDFError("This file isn't a PDF.")
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:  # PyMuPDF raises several unrelated types for corrupt files
        raise PDFError("The PDF is damaged or can't be opened.") from exc

    with doc:
        if doc.needs_pass:
            raise PDFError("The PDF is password-protected.")
        if doc.page_count > max_pages:
            raise PDFError(f"The PDF has {doc.page_count} pages; the limit is {max_pages}.")
        pages = [
            Page(number=i, text=text)
            for i, page in enumerate(doc.pages(), start=1)
            if (text := clean_text(page.get_text("text")))
        ]

    if not pages:
        raise PDFError("No text found. The PDF may be scanned images, which need OCR first.")
    return pages
