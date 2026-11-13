"""OCR of scanned pages (Tesseract is simulated, so these run without it installed)."""

import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding

from backend import pdf
from backend.main import create_app
from backend.rag import assess
from backend.schemas import Source
from backend.tests.conftest import connect, make_pdf, upload

SCANNED_TEXT = "1. Retention\n1.1 Records are kept for 7 years.\n2. Disposal\n2.1 Shred paper.\n3. Other\n3.1 None."


@pytest.fixture
def fake_tesseract(monkeypatch):
    monkeypatch.setattr(pdf, "ocr_available", lambda: True)
    monkeypatch.setattr(pdf, "_ocr_page", lambda page: SCANNED_TEXT)


def test_scanned_pages_are_ocrd_and_flagged(fake_tesseract):
    pages = pdf.extract_pages(make_pdf("Typed page with plenty of real text on it for sure.", ""))
    assert [(p.number, p.ocr) for p in pages] == [(1, False), (2, True)]
    assert pages[1].text.startswith("1. Retention")


def test_without_tesseract_a_scan_gets_a_clear_message(monkeypatch):
    monkeypatch.setattr(pdf, "ocr_available", lambda: False)
    with pytest.raises(pdf.PDFError, match="brew install tesseract"):
        pdf.extract_pages(make_pdf(""))


def test_ocr_can_be_turned_off(fake_tesseract):
    with pytest.raises(pdf.PDFError, match="No text found"):
        pdf.extract_pages(make_pdf(""), ocr=False)


def test_ocr_page_cap(fake_tesseract):
    pages = pdf.extract_pages(make_pdf("", "", ""), max_ocr_pages=2)
    assert [p.number for p in pages] == [1, 2]


def test_ocr_sources_are_flagged_and_never_strong(fake_tesseract, settings, fake_llm):
    fake_llm.answers = ["Records are kept for 7 years [1]."]
    app = create_app(settings, embeddings=DeterministicFakeEmbedding(size=32), llm=fake_llm.model())
    with connect(app) as c:
        upload(c, "Scan.pdf", make_pdf(""))
        body = c.post("/w/ask", json={"question": "How long are records kept?"}).json()
        cited = [s for s in body["sources"] if s["n"] in body["cited"]]
        assert cited and all(s["ocr"] for s in cited)
        assert body["confidence"] != "high"
    strong = Source(n=1, document_id="d", filename="f", page=1, snippet="", score=0.99, ocr=True)
    assert assess("Yes [1].", [strong], [1], 0.7, 0.6) == (True, "medium")
