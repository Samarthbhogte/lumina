"""One shared document store: a FAISS index of page-level chunks plus a JSON manifest.

The app creates a single DocumentStore at startup and every route uses it, so a
document is searchable the moment its upload finishes.

On-disk layout (under settings.data_dir):
    documents.json   manifest of documents, the chunk ids each owns, and a checksum of the index
    index/           FAISS index (index.faiss + index.pkl), written only by this class
    files/<id>.pdf   the original upload, served for citations and used to rebuild the index

Concurrency: one process owns the data directory. Run a single uvicorn worker, and add
documents through the API (backend/scripts/ingest_folder.py does) rather than opening a
second DocumentStore on the same directory. Slow work (PDF embedding, query embedding)
happens outside the lock; the lock only covers in-memory mutation and the disk writes.
"""

import hashlib
import json
import logging
import os
import shutil
import threading
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from langchain_community.vectorstores import FAISS
from langchain_community.vectorstores.utils import DistanceStrategy
from langchain_core.embeddings import Embeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from backend.pdf import Page, extract_pages

logger = logging.getLogger(__name__)

MANIFEST_VERSION = 2
IP = DistanceStrategy.MAX_INNER_PRODUCT


class DocumentTooLarge(ValueError):
    """The document would produce more chunks than allowed. The message is user-facing."""


@dataclass
class DocumentRecord:
    id: str
    filename: str
    sha256: str
    pages: int
    chunks: int
    size_bytes: int
    uploaded_at: str
    chunk_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SearchHit:
    text: str
    document_id: str
    filename: str
    page: int
    # Inner product. OpenAI embeddings are unit-length, so this is cosine similarity:
    # roughly 0 (unrelated) to 1 (identical).
    score: float


@dataclass
class _Chunks:
    texts: list[str]
    metadatas: list[dict]
    ids: list[str]


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DocumentStore:
    def __init__(
        self,
        data_dir: Path,
        embeddings: Embeddings,
        chunk_size: int = 1000,
        chunk_overlap: int = 150,
        max_chunks: int = 4000,
    ):
        self.data_dir = Path(data_dir)
        self.index_dir = self.data_dir / "index"
        self.files_dir = self.data_dir / "files"
        self.manifest_path = self.data_dir / "documents.json"
        self.files_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.data_dir, 0o700)

        self._embeddings = embeddings
        self._splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        self._max_chunks = max_chunks
        self._lock = threading.RLock()
        self._docs, index_sha = self._load_manifest()
        self._index: FAISS | None = self._load_index(index_sha)

    # ---------- persistence ----------

    def _load_manifest(self) -> tuple[dict[str, DocumentRecord], str | None]:
        if not self.manifest_path.exists():
            return {}, None
        try:
            raw = json.loads(self.manifest_path.read_text())
            docs = {d["id"]: DocumentRecord(**d) for d in raw.get("documents", [])}
            return docs, raw.get("index_sha256")
        except (ValueError, TypeError, KeyError) as exc:
            backup = self.manifest_path.with_suffix(f".corrupt-{int(datetime.now().timestamp())}.json")
            os.replace(self.manifest_path, backup)
            logger.error("Manifest unreadable (%s); moved to %s and starting empty", exc, backup.name)
            return {}, None

    def _save_manifest(self) -> None:
        pkl = self.index_dir / "index.pkl"
        payload = {
            "version": MANIFEST_VERSION,
            "index_sha256": _sha256_file(pkl) if pkl.exists() else None,
            "documents": [asdict(d) for d in self._docs.values()],
        }
        tmp = self.manifest_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2))
        os.replace(tmp, self.manifest_path)

    def _load_index(self, expected_sha: str | None) -> FAISS | None:
        old = self.index_dir.with_name("index.old")
        if not self.index_dir.exists() and old.exists():
            old.rename(self.index_dir)  # crash between the two renames in _save_index
        pkl = self.index_dir / "index.pkl"
        if not self._docs:
            return None
        if pkl.exists() and expected_sha and _sha256_file(pkl) == expected_sha:
            try:
                # The pickle is written only by this class, and its checksum (above) must
                # match the manifest, so a torn or swapped file is never deserialised.
                return FAISS.load_local(
                    str(self.index_dir), self._embeddings, allow_dangerous_deserialization=True, distance_strategy=IP
                )
            except Exception:
                logger.exception("FAISS index failed to load")
        logger.warning("Index missing or does not match the manifest; rebuilding from stored PDFs")
        return self._rebuild()

    def _rebuild(self) -> FAISS | None:
        index: FAISS | None = None
        for record in list(self._docs.values()):
            path = self.file_path(record.id)
            try:
                chunks = self._chunk(record.id, record.filename, extract_pages(path.read_bytes()))
                vectors = self._embeddings.embed_documents(chunks.texts)
            except Exception:
                logger.exception("Could not re-index %s; it stays listed but unsearchable", record.filename)
                continue
            pairs = list(zip(chunks.texts, vectors, strict=True))
            if index is None:
                index = FAISS.from_embeddings(
                    pairs, self._embeddings, metadatas=chunks.metadatas, ids=chunks.ids, distance_strategy=IP
                )
            else:
                index.add_embeddings(pairs, metadatas=chunks.metadatas, ids=chunks.ids)
            record.chunk_ids, record.chunks = chunks.ids, len(chunks.ids)
        if index is None:
            return None  # nothing re-indexed (e.g. no API key yet): leave files on disk untouched
        self._index = index
        self._save_index()
        self._save_manifest()
        return index

    def _save_index(self) -> None:
        """Write the index to a temp dir, then swap it in, so a crash never leaves half a pair."""
        if self._index is None or self._index.index.ntotal == 0:
            self._index = None
            shutil.rmtree(self.index_dir, ignore_errors=True)
            return
        tmp = self.index_dir.with_name(f"index.tmp-{uuid.uuid4().hex[:8]}")
        old = self.index_dir.with_name("index.old")
        self._index.save_local(str(tmp))
        shutil.rmtree(old, ignore_errors=True)
        if self.index_dir.exists():
            self.index_dir.rename(old)
        tmp.rename(self.index_dir)
        shutil.rmtree(old, ignore_errors=True)

    # ---------- queries ----------

    def list_documents(self) -> list[DocumentRecord]:
        with self._lock:
            return sorted(self._docs.values(), key=lambda d: d.uploaded_at, reverse=True)

    def get(self, document_id: str) -> DocumentRecord | None:
        with self._lock:
            return self._docs.get(document_id)

    def file_path(self, document_id: str) -> Path:
        return self.files_dir / f"{document_id}.pdf"

    @property
    def chunk_count(self) -> int:
        with self._lock:
            return sum(d.chunks for d in self._docs.values())

    def find_by_hash(self, sha256: str) -> DocumentRecord | None:
        with self._lock:
            return next((d for d in self._docs.values() if d.sha256 == sha256), None)

    def search(self, query: str, k: int = 6, document_ids: list[str] | None = None) -> list[SearchHit]:
        with self._lock:
            if self._index is None:
                return []
        vector = self._embeddings.embed_query(query)  # network call: outside the lock
        with self._lock:
            if self._index is None:
                return []
            kwargs: dict = {}
            if document_ids:
                allowed = set(document_ids)
                filt: Callable[[dict], bool] = lambda md: md.get("document_id") in allowed  # noqa: E731
                # FAISS filters after fetching fetch_k neighbours. A flat index is cheap to
                # scan fully, and anything smaller can miss small documents entirely.
                kwargs = {"filter": filt, "fetch_k": self._index.index.ntotal}
            results = self._index.similarity_search_with_score_by_vector(vector, k=k, **kwargs)
        return [
            SearchHit(
                text=doc.page_content,
                document_id=doc.metadata["document_id"],
                filename=doc.metadata["filename"],
                page=doc.metadata["page"],
                score=float(score),
            )
            for doc, score in results
        ]

    # ---------- mutations ----------

    def _chunk(self, doc_id: str, filename: str, pages: list[Page]) -> _Chunks:
        texts, metas = [], []
        for page in pages:
            for text in self._splitter.split_text(page.text):
                texts.append(text)
                metas.append({"document_id": doc_id, "filename": filename, "page": page.number})
        if len(texts) > self._max_chunks:
            raise DocumentTooLarge(
                f"This document has too much text ({len(texts)} chunks; the limit is {self._max_chunks})."
            )
        return _Chunks(texts=texts, metadatas=metas, ids=[uuid.uuid4().hex for _ in texts])

    def add(self, filename: str, data: bytes, pages: list[Page]) -> tuple[DocumentRecord, bool]:
        """Index a parsed PDF. Returns (record, created); created is False for a duplicate."""
        sha256 = hashlib.sha256(data).hexdigest()
        if existing := self.find_by_hash(sha256):
            return existing, False

        doc_id = uuid.uuid4().hex
        chunks = self._chunk(doc_id, filename, pages)
        vectors = self._embeddings.embed_documents(chunks.texts)  # slow network call: outside the lock
        pairs = list(zip(chunks.texts, vectors, strict=True))

        with self._lock:
            if existing := self.find_by_hash(sha256):  # same file uploaded concurrently
                return existing, False
            created_index = self._index is None
            try:
                if created_index:
                    self._index = FAISS.from_embeddings(
                        pairs, self._embeddings, metadatas=chunks.metadatas, ids=chunks.ids, distance_strategy=IP
                    )
                else:
                    self._index.add_embeddings(pairs, metadatas=chunks.metadatas, ids=chunks.ids)
                self.file_path(doc_id).write_bytes(data)
                record = DocumentRecord(
                    id=doc_id,
                    filename=filename,
                    sha256=sha256,
                    pages=len(pages),
                    chunks=len(chunks.ids),
                    size_bytes=len(data),
                    uploaded_at=datetime.now(UTC).isoformat(timespec="seconds"),
                    chunk_ids=chunks.ids,
                )
                self._docs[doc_id] = record
                self._save_index()
                self._save_manifest()
            except Exception:
                # Undo everything so the index never holds chunks the manifest doesn't own.
                self._docs.pop(doc_id, None)
                if created_index:
                    self._index = None
                elif self._index is not None:
                    self._delete_chunks(chunks.ids)
                self.file_path(doc_id).unlink(missing_ok=True)
                raise
        logger.info("Indexed %s: %d pages, %d chunks", filename, len(pages), len(chunks.ids))
        return record, True

    def _delete_chunks(self, chunk_ids: list[str]) -> None:
        if self._index is None:
            return
        present = set(self._index.index_to_docstore_id.values())
        ids = [i for i in chunk_ids if i in present]  # FAISS.delete raises on unknown ids
        if ids:
            self._index.delete(ids)

    def delete(self, document_id: str) -> bool:
        with self._lock:
            record = self._docs.get(document_id)
            if record is None:
                return False
            self._delete_chunks(record.chunk_ids)
            del self._docs[document_id]
            self._save_index()
            self._save_manifest()
            self.file_path(document_id).unlink(missing_ok=True)
        logger.info("Deleted %s (%s)", record.filename, document_id)
        return True
