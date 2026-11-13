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
    assert reference_boost("What does 3.2 say?", md) == 0.05
    assert reference_boost("Summarise section 3", md) == 0.02
    assert reference_boost("Release version 3.2 notes", md) == 0.0  # no cue word
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


# ---------- review findings: real-world structure ----------


def _sections_of(text_pages, **kw):
    pages = [Page(i, t) for i, t in enumerate(text_pages, 1)]
    return chunk_document(pages, "d", "x.pdf", **kw)


def test_table_of_contents_with_leaders_is_not_headings():
    toc = "Contents\n1. Scope ........ 2\n2. Rules ........ 3\n3. Retention ........ 4\n"
    body = "1. Scope\n1.1 Covers staff.\n2. Rules\n2.1 Be careful.\n3. Retention\n3.1 Keep 30 days."
    chunks = _sections_of([toc + body])
    s3 = next(c for c in chunks if c.metadata.get("section") == "3")
    assert s3.metadata["clauses"] == {"3.1": [1, 1]} and "Keep 30 days" in s3.text


def test_unmarked_contents_list_is_discarded_when_numbering_restarts():
    toc = "1. Scope\n2. Rules\n3. Retention\n4. Contact\n"
    body = (
        "1. Scope\n1.1 Covers staff.\n2. Rules\n2.1 Be careful.\n"
        "3. Retention\n3.1 Keep 30 days.\n4. Contact\n4.1 Email us."
    )
    chunks = _sections_of([toc + body])
    assert [c.metadata.get("section") for c in chunks if c.metadata.get("section")] == ["1", "2", "3", "4"]
    assert all(c.metadata["clauses"] for c in chunks if c.metadata.get("section"))


def test_stray_large_number_does_not_swallow_headings():
    text = "1. Alpha\n1.1 a.\n2. Beta\n2.1 b.\n99. Main Street office\n3. Gamma\n3.1 c.\n4. Delta\n4.1 d."
    sections = [c.metadata.get("section") for c in _sections_of([text])]
    assert sections[-2:] == ["3", "4"]


def test_multi_level_and_trailing_dot_clauses():
    text = "1. Alpha\n1.1 Top.\n1.1.1 Deeper detail.\n1.2. With trailing dot.\n2. Beta\n2.1 b.\n3. Gamma\n3.1 c."
    s1 = next(c for c in _sections_of([text]) if c.metadata.get("section") == "1")
    assert set(s1.metadata["clauses"]) == {"1.1", "1.1.1", "1.2"}


def test_decimal_at_line_start_in_prose_is_not_a_clause():
    text = "1. Alpha\n1.1 Fees rise by\n2.5 percent each year.\n2. Beta\n2.1 b.\n3. Gamma\n3.1 c."
    s1 = next(c for c in _sections_of([text]) if c.metadata.get("section") == "1")
    assert s1.metadata["clauses"] == {"1.1": [1, 1]} and "Fees rise by 2.5 percent" in s1.text


def test_repeated_header_and_footer_lines_are_dropped():
    pages = [f"ACME CONFIDENTIAL\n{n}. Part {n}\n{n}.1 Text {n}.\nPage footer v1" for n in (1, 2, 3)]
    chunks = _sections_of(pages)
    assert not any("ACME CONFIDENTIAL" in c.text or "Page footer" in c.text for c in chunks)


def test_long_section_without_clauses_is_still_split():
    long = "Background paragraph. " * 300  # ~6,600 chars, no clause lines
    chunks = _sections_of([f"1. Alpha\n1.1 a.\n2. Long\n{long}\n3. Gamma\n3.1 c."], chunk_size=1000)
    assert max(len(c.text) for c in chunks) <= 1500
    assert sum(c.metadata.get("section") == "2" for c in chunks) > 3


def test_named_clause_is_retrieved_even_if_retrievers_miss_it(tmp_path):
    store = DocumentStore(tmp_path, DeterministicFakeEmbedding(size=32))
    filler = "\n".join(f"{i}. Topic {i}\n{i}.1 General statement number {i}." for i in range(1, 30))
    store.add("big.pdf", b"x", [Page(1, filler)])
    hits = store.search("What does clause 17.1 say?", k=3)
    assert hits[0].section == "17"
