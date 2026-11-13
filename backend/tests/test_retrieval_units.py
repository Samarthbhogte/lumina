from pathlib import Path

from langchain_core.embeddings import DeterministicFakeEmbedding

from backend.chunking import chunk_document
from backend.citations import best_clause, citing_sentences, document_name, section_label
from backend.hybrid import Entry, KeywordIndex, fuse, reference_boost
from backend.pdf import Page, extract_pages
from backend.store import DocumentStore

SAMPLES = Path(__file__).resolve().parents[2] / "samples"


def _gdpr_chunks():
    data = (SAMPLES / "GDPR_Sample_Compliance.pdf").read_bytes()
    return chunk_document(extract_pages(data), "d", "GDPR_Sample_Compliance.pdf")


def test_section_chunk_keeps_clause_that_crosses_page_break():
    s7 = next(c for c in _gdpr_chunks() if c.metadata.get("section") == "7")
    assert s7.metadata["heading"] == "Breach Notification"
    assert s7.metadata["clauses"] == {"7.1": [1, 1], "7.2": [1, 2]}
    assert "statutory timelines when required." in s7.text  # "required." is on page 2
    assert s7.search_text.startswith("GDPR SAMPLE COMPLIANCE (SIMULATED) > 7. Breach Notification")


def test_unstructured_document_falls_back_to_page_splitting():
    pages = [Page(1, "Plain prose about retention. " * 20), Page(2, "More prose without headings.")]
    chunks = chunk_document(pages, "d", "memo.pdf", chunk_size=200, chunk_overlap=0)
    assert chunks and all("section" not in c.metadata for c in chunks)
    assert {c.metadata["page"] for c in chunks} == {1, 2}


def test_headings_must_increase():
    text = "1. Scope\n1.1 Applies here.\n2. Rules\n2.1 Do things.\n1. Not A Heading\n3. Final\n3.1 Done."
    chunks = chunk_document([Page(1, text)], "d", "x.pdf")
    assert [c.metadata.get("section") for c in chunks] == ["1", "2", "3"]
    assert "1. Not A Heading" in chunks[1].text


def test_long_section_splits_at_clause_boundaries():
    clauses = "\n".join(f"4.{i} " + "word " * 60 for i in range(1, 6))
    pages = [Page(1, f"1. Alpha\n1.1 x\n2. Beta\n2.1 y\n4. Long Section\n{clauses}")]
    parts = [c for c in chunk_document(pages, "d", "x.pdf", chunk_size=400) if c.metadata.get("section") == "4"]
    assert len(parts) > 1 and parts[1].text.startswith("4. Long Section (continued)")
    assert all(any(c.startswith("4.") for c in p.metadata["clauses"]) for p in parts)


def test_keyword_index_finds_exact_terms_and_respects_filter():
    idx = KeywordIndex(
        [
            Entry("a", "doc1", "Access to CPNI requires authentication"),
            Entry("b", "doc2", "Robocall mitigation with STIR/SHAKEN"),
            Entry("c", "doc2", "Retention schedules"),
        ]
    )
    assert idx.search("Who may access CPNI?")[0] == "a"
    assert idx.search("robocalls")[0] == "b"  # stemming
    assert idx.search("CPNI", allowed={"doc2"}) == []
    assert idx.search("zzzz unknown words") == []


def test_fusion_and_reference_boost():
    scores = fuse(["a", "b"], ["b", "c"])
    assert max(scores, key=scores.get) == "b"
    md = {"section": "3", "clauses": {"3.2": [1, 1]}}
    assert reference_boost("What does 3.2 say?", md) == 1.0
    assert reference_boost("Summarise section 3", md) == 0.5
    assert reference_boost("What does 4.1 say?", md) == 0.0


def test_store_clause_reference_beats_similar_text(tmp_path):
    store = DocumentStore(tmp_path, DeterministicFakeEmbedding(size=32))
    text = (
        "1. Consent\n1.1 Consent is logged.\n1.2 Users may withdraw consent.\n"
        "2. Retention\n2.1 Kept 30 days.\n3. Other\n3.1 None."
    )
    store.add("policy.pdf", b"p", [Page(1, text)])
    assert store.search("what does 2.1 say", k=1)[0].section == "2"


def test_labels_and_clause_choice():
    assert document_name("GDPR_Sample_Compliance.pdf") == "GDPR Sample Compliance"
    assert section_label("GDPR_Sample_Compliance.pdf", 1, 2, "7") == "GDPR Sample Compliance §7, pp.1–2"
    assert section_label("memo.pdf", 3, 3, None) == "memo, p.3"
    chunk = (
        "7. Breach Notification\n7.1 Incidents are triaged and documented.\n"
        "7.2 Notices to authorities follow statutory timelines."
    )
    clauses = {"7.1": [1, 1], "7.2": [1, 2]}
    answer = "Incidents get triaged [1]. Notices to authorities follow statutory timelines [2][1]."
    assert citing_sentences(answer, 2) == "Notices to authorities follow statutory timelines [2][1]."
    assert best_clause(chunk, citing_sentences(answer, 2), clauses) == "7.2"
    assert best_clause(chunk, "Something unrelated [1].", clauses) is None
