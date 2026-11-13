"""PDF text extraction, page by page, so answers can cite page numbers.

Pages without a text layer (scans) are read with OCR when Tesseract is installed
(`brew install tesseract`, or `tesseract-ocr` in Docker). OCR runs locally; no page image
leaves the machine. OCR'd pages are flagged so citations and confidence can say so.
"""

import logging
import re
from dataclasses import dataclass
from functools import lru_cache

import pymupdf as fitz


class PDFError(ValueError):
    """The file can't be turned into searchable text. The message is shown to the user."""


logger = logging.getLogger(__name__)

MIN_TEXT_CHARS = 30  # pages with less extractable text than this are treated as scans
OCR_DPI = 300


@dataclass(frozen=True)
class Page:
    number: int  # 1-based
    text: str
    ocr: bool = False  # text came from OCR, not the PDF's own text layer


@lru_cache
def ocr_available() -> bool:
    try:
        return bool(fitz.get_tessdata())
    except Exception:
        return False


def _ocr_page(page) -> str:
    textpage = page.get_textpage_ocr(language="eng", dpi=OCR_DPI, full=True)
    return page.get_text("text", textpage=textpage)


_HYPHEN_BREAK = re.compile(r"(\w)-\n(\w)")
_SPACES = re.compile(r"[ \t ]+")
_BLANK_LINES = re.compile(r"\n{3,}")


def clean_text(text: str) -> str:
    text = _HYPHEN_BREAK.sub(r"\1\2", text)
    text = _SPACES.sub(" ", text)
    text = "\n".join(line.strip() for line in text.splitlines())
    return _BLANK_LINES.sub("\n\n", text).strip()


def extract_pages(data: bytes, max_pages: int = 1000, ocr: bool = True, max_ocr_pages: int = 50) -> list[Page]:
    """Return the non-empty pages of a PDF. Raises PDFError with a user-facing reason."""
    if not data.startswith(b"%PDF-"):
        raise PDFError("This file isn't a PDF.")
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:  # PyMuPDF raises several unrelated types for corrupt files
        raise PDFError("The PDF is damaged or can't be opened.") from exc

    use_ocr = ocr and ocr_available()
    scanned = 0
    pages: list[Page] = []
    with doc:
        if doc.needs_pass:
            raise PDFError("The PDF is password-protected.")
        if doc.page_count > max_pages:
            raise PDFError(f"The PDF has {doc.page_count} pages; the limit is {max_pages}.")
        for i, page in enumerate(doc.pages(), start=1):
            text = clean_text(page.get_text("text"))
            if len(text) >= MIN_TEXT_CHARS:
                pages.append(Page(number=i, text=text))
                continue
            scanned += 1
            if use_ocr and scanned <= max_ocr_pages:
                try:
                    ocr_text = clean_text(_ocr_page(page))
                except Exception:
                    logger.exception("OCR failed on page %d", i)
                    ocr_text = ""
                if ocr_text:
                    pages.append(Page(number=i, text=ocr_text, ocr=True))
                    continue
            if text:
                pages.append(Page(number=i, text=text))

    if scanned > max_ocr_pages and use_ocr:
        logger.warning("Only the first %d of %d scanned pages were OCR'd", max_ocr_pages, scanned)
    if not pages:
        if ocr and not ocr_available():
            raise PDFError(
                "No text found: this looks like a scanned PDF. Install Tesseract on the server "
                "(macOS: brew install tesseract) to read scans, then upload it again."
            )
        raise PDFError("No text found. The PDF may be blank or contain only images.")
    return pages
