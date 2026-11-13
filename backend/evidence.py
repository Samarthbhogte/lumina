"""Evidence packs: an auditor-ready PDF of recorded answers, with a verifiable integrity hash.

A pack is built only from the server's own answer records (never from what a browser
sends), so it shows exactly what Lumina answered, from which passages and document
versions, with which model, when and for whom.

Integrity: the pack's canonical JSON is embedded in the PDF as `evidence.json`, and its
SHA-256 is printed on every page and stored in the PDF metadata. `verify_pack()` recomputes
it, so any edit to the recorded content is detectable. (This proves the content hasn't
changed since export; it is not a signature proving who exported it.)
"""

import hashlib
import html
import io
import json
import re
from datetime import UTC, datetime

import pymupdf

PACK_VERSION = 1
HASH_PREFIX = "lumina-evidence-sha256:"
DISCLAIMER = (
    "Lumina answers only from the documents listed and does not give legal advice. A "
    "“strong source match” means the cited passages closely match the question, not that "
    "the answer is legally correct. Verify every excerpt against the cited page before relying on it."
)


def canonical(record: dict) -> bytes:
    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def digest(record: dict) -> str:
    return hashlib.sha256(canonical(record)).hexdigest()


def answer_entry(question: str, payload: dict) -> dict:
    """One recorded answer, from a stored assistant message payload."""
    response = payload["response"]
    excerpts = payload.get("excerpts") or {}
    docs = payload.get("documents") or {}
    sources = []
    for s in response.get("sources", []):
        doc = docs.get(s["document_id"], {})
        sources.append(
            {
                "n": s["n"],
                "cited": s["n"] in response.get("cited", []),
                "label": s.get("label") or f"{s['filename']}, p.{s['page']}",
                "filename": s["filename"],
                "page": s["page"],
                "page_end": s.get("page_end"),
                "section": s.get("section"),
                "clause": s.get("clause"),
                "similarity": s["score"],
                "excerpt": excerpts.get(str(s["n"])) or s.get("snippet", ""),
                "ocr": bool(s.get("ocr")),
                "document_sha256": doc.get("sha256"),
                "document_uploaded_at": doc.get("uploaded_at"),
            }
        )
    return {
        "message_id": response.get("message_id"),
        "question": question,
        "search_query": payload.get("search_query"),
        "answer": response["answer"],
        "found": response["found"],
        "flagged": response.get("flagged", False),
        "confidence": response["confidence"],
        "confidence_thresholds": payload.get("thresholds"),
        "provider": payload.get("provider"),
        "model": response.get("model"),
        "embedding_model": payload.get("embedding_model"),
        "document_filter": payload.get("document_filter"),
        "answered_at": payload.get("answered_at"),
        "sources": sources,
    }


def build_record(workspace: dict, exported_by: dict, conversation: dict, answers: list[dict], app_version: str) -> dict:
    return {
        "pack_version": PACK_VERSION,
        "app": {"name": "Lumina", "version": app_version},
        "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "exported_by": exported_by,
        "workspace": workspace,
        "conversation": conversation,
        "answers": answers,
        "disclaimer": DISCLAIMER,
    }


# ---------- PDF ----------

_CSS = """
body { font-family: sans-serif; font-size: 9.5pt; color: #1c1b19; line-height: 1.4; }
h1 { font-size: 18pt; margin: 0 0 4pt 0; }
h2 { font-size: 12pt; margin: 14pt 0 4pt 0; border-bottom: 1px solid #e3ded4; padding-bottom: 2pt; }
h3 { font-size: 10pt; margin: 8pt 0 2pt 0; }
p { margin: 2pt 0; }
.muted { color: #5c5851; }
.small { font-size: 8pt; }
.answer { font-family: serif; font-size: 10.5pt; margin: 4pt 0 6pt 0; }
.excerpt { font-family: serif; margin: 2pt 0 6pt 10pt; padding-left: 6pt; border-left: 2px solid #9a5706; }
table { border-collapse: collapse; margin: 4pt 0; }
td { padding: 1pt 8pt 1pt 0; vertical-align: top; }
.badge { font-weight: bold; }
"""


def _e(text) -> str:
    return html.escape(str(text if text is not None else "—"))


def _plain(markdown: str) -> str:
    """Answers are Markdown; the pack shows them as plain paragraphs, keeping [n] markers."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", markdown)
    return re.sub(r"^\s*[-*]\s+", "• ", text, flags=re.MULTILINE)


def _html(record: dict, sha: str) -> str:
    ws, by, conv = record["workspace"], record["exported_by"], record["conversation"]
    parts = [
        "<h1>Lumina evidence pack</h1>",
        f"<p class='muted'>{_e(conv.get('title'))}</p>",
        "<table>",
        f"<tr><td class='muted'>Workspace</td><td>{_e(ws['name'])} ({_e(ws['id'])})</td></tr>",
        f"<tr><td class='muted'>Exported by</td><td>{_e(by['display_name'])} &lt;{_e(by['email'])}&gt;</td></tr>",
        f"<tr><td class='muted'>Exported at (UTC)</td><td>{_e(record['exported_at'].replace('+00:00', 'Z'))}</td></tr>",
        f"<tr><td class='muted'>Answers</td><td>{len(record['answers'])}</td></tr>",
        f"<tr><td class='muted'>Integrity (SHA-256)</td><td class='small'>{_e(sha)}</td></tr>",
        "</table>",
        f"<p class='small muted'>{_e(record['disclaimer'])}</p>",
    ]
    for i, a in enumerate(record["answers"], 1):
        strength = {"high": "Strong source match", "medium": "Partial source match", "low": "Weak source match"}
        status = (
            "Blocked as a prompt-injection attempt"
            if a["flagged"]
            else "Not found in the documents"
            if not a["found"]
            else strength.get(a["confidence"], a["confidence"])
        )
        parts += [
            f"<h2>{i}. {_e(a['question'])}</h2>",
            f"<p class='answer'>{'<br/>'.join(_e(line) for line in _plain(a['answer']).splitlines())}</p>",
            f"<p><span class='badge'>{_e(status)}</span> <span class='muted small'>· answered {_e(a['answered_at'])} "
            f"by {_e(a['provider'])} {_e(a['model'])} · embeddings {_e(a['embedding_model'])}</span></p>",
        ]
        cited = [s for s in a["sources"] if s["cited"]]
        other = [s for s in a["sources"] if not s["cited"]]
        if cited:
            parts.append("<h3>Cited passages</h3>")
        for s in cited:
            sha16 = (s["document_sha256"] or "")[:16]
            meta = (
                f"similarity {s['similarity']:.3f} · document sha256 {_e(sha16)}… "
                f"· uploaded {_e(s['document_uploaded_at'])}"
            )
            excerpt = "<br/>".join(_e(line) for line in s["excerpt"].splitlines())
            ocr_note = " <i>(OCR text: verify against the page image)</i>" if s.get("ocr") else ""
            parts += [
                f"<p><b>[{s['n']}] {_e(s['label'])}</b>{ocr_note} <span class='muted small'>· {meta}</span></p>",
                f"<p class='excerpt'>{excerpt}</p>",
            ]
        if other:
            parts.append("<h3>Retrieved but not cited</h3>")
            parts.append("<p class='small muted'>" + "; ".join(f"[{s['n']}] {_e(s['label'])}" for s in other) + "</p>")
    return "\n".join(parts)


def render_pdf(record: dict) -> bytes:
    sha = digest(record)
    buffer = io.BytesIO()
    writer = pymupdf.DocumentWriter(buffer)
    story = pymupdf.Story(_html(record, sha), user_css=_CSS)
    page = pymupdf.paper_rect("a4")
    body = page + (54, 54, -54, -64)
    more = True
    while more:
        device = writer.begin_page(page)
        more, _ = story.place(body)
        story.draw(device)
        writer.end_page()
    writer.close()

    doc = pymupdf.open("pdf", buffer.getvalue())
    for number, p in enumerate(doc, 1):
        p.insert_text(
            (54, page.height - 36),
            f"Lumina evidence pack · SHA-256 {sha} · page {number} of {doc.page_count}",
            fontsize=6.5,
            color=(0.36, 0.35, 0.32),
        )
    doc.embfile_add("evidence.json", canonical(record), desc="Canonical record; its SHA-256 is printed on each page")
    doc.set_metadata(
        {
            "title": "Lumina evidence pack",
            "author": "Lumina",
            "subject": record["conversation"].get("title") or "",
            "keywords": f"{HASH_PREFIX}{sha}",
        }
    )
    data = doc.tobytes(garbage=3, deflate=True)
    doc.close()
    return data


def verify_pack(pdf: bytes) -> tuple[bool, str, dict | None]:
    """(valid, message, record). Valid when the embedded record still matches its hash."""
    try:
        doc = pymupdf.open("pdf", pdf)
    except Exception:
        return False, "Not a readable PDF.", None
    with doc:
        keywords = doc.metadata.get("keywords") or ""
        if not keywords.startswith(HASH_PREFIX) or "evidence.json" not in doc.embfile_names():
            return False, "This PDF is not a Lumina evidence pack.", None
        expected = keywords[len(HASH_PREFIX) :]
        record = json.loads(doc.embfile_get("evidence.json"))
    actual = digest(record)
    if actual != expected:
        return False, f"Modified: the recorded content hashes to {actual}, but the pack claims {expected}.", record
    return True, f"Intact: SHA-256 {actual} matches.", record
