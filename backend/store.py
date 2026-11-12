"""One shared document store: a FAISS index of page-level chunks plus a JSON manifest.

The app creates a single DocumentStore at startup and every route uses it, so a
document is searchable the moment its upload finishes.

On-disk layout (under settings.data_dir):
    documents.json   manifest of uploaded documents and the chunk ids they own
    index/           FAISS index (index.faiss + index.pkl), written only by this class
    files/<id>.pdf   the original upload, served so citations can open the cited page
"""

import hashlib
import json
import logging
import os
import shutil
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from langchain_community.vectorstores import FAISS
from langchain_community.vectorstores.utils import DistanceStrategy
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from backend.pdf import Page

logger = logging.getLogger(__name__)

MANIFEST_VERSION = 1


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


class DocumentStore:
    def __init__(
        self,
        data_dir: Path,
        embeddings: Embeddings,
        chunk_size: int = 1000,
        chunk_overlap: int = 150,
    ):
        self.data_dir = Path(data_dir)
        self.index_dir = self.data_dir / "index"
        self.files_dir = self.data_dir / "files"
        self.manifest_path = self.data_dir / "documents.json"
        self.files_dir.mkdir(parents=True, exist_ok=True)

        self._embeddings = embeddings
        self._splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        self._lock = threading.RLock()
        self._docs: dict[str, DocumentRecord] = self._load_manifest()
        self._index: FAISS | None = self._load_index()

    # ---------- persistence ----------

    def _load_manifest(self) -> dict[str, DocumentRecord]:
        if not self.manifest_path.exists():
            return {}
        raw = json.loads(self.manifest_path.read_text())
        return {d["id"]: DocumentRecord(**d) for d in raw.get("documents", [])}

    def _save_manifest(self) -> None:
        payload = {
            "version": MANIFEST_VERSION,
            "documents": [asdict(d) for d in self._docs.values()],
        }
        tmp = self.manifest_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2))
        os.replace(tmp, self.manifest_path)

    def _load_index(self) -> FAISS | None:
        if not (self.index_dir / "index.faiss").exists():
            return None
        # The pickle half of the index is written only by this class, never uploaded,
        # so deserialising it is safe here. Never point index_dir at untrusted files.
        return FAISS.load_local(
            str(self.index_dir),
            self._embeddings,
            allow_dangerous_deserialization=True,
            distance_strategy=DistanceStrategy.MAX_INNER_PRODUCT,
        )

    def _save_index(self) -> None:
        if self._index is None or self._index.index.ntotal == 0:
            self._index = None
            shutil.rmtree(self.index_dir, ignore_errors=True)
            return
        self._index.save_local(str(self.index_dir))

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
            kwargs = {}
            if document_ids:
                allowed = set(document_ids)
                kwargs = {
                    "filter": lambda md: md.get("document_id") in allowed,
                    "fetch_k": max(50, k * 10),
                }
            results = self._index.similarity_search_with_score(query, k=k, **kwargs)
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

    def add(self, filename: str, data: bytes, pages: list[Page]) -> tuple[DocumentRecord, bool]:
        """Index a parsed PDF. Returns (record, created); created is False for a duplicate."""
        sha256 = hashlib.sha256(data).hexdigest()
        with self._lock:
            if existing := self.find_by_hash(sha256):
                return existing, False

            doc_id = uuid.uuid4().hex
            chunks: list[Document] = []
            for page in pages:
                for text in self._splitter.split_text(page.text):
                    chunks.append(
                        Document(
                            page_content=text,
                            metadata={"document_id": doc_id, "filename": filename, "page": page.number},
                        )
                    )
            chunk_ids = [uuid.uuid4().hex for _ in chunks]

            # Embed first: if the OpenAI call fails, nothing has been written yet.
            if self._index is None:
                self._index = FAISS.from_documents(
                    chunks,
                    self._embeddings,
                    ids=chunk_ids,
                    distance_strategy=DistanceStrategy.MAX_INNER_PRODUCT,
                )
            else:
                self._index.add_documents(chunks, ids=chunk_ids)

            self.file_path(doc_id).write_bytes(data)
            record = DocumentRecord(
                id=doc_id,
                filename=filename,
                sha256=sha256,
                pages=len(pages),
                chunks=len(chunks),
                size_bytes=len(data),
                uploaded_at=datetime.now(UTC).isoformat(timespec="seconds"),
                chunk_ids=chunk_ids,
            )
            self._docs[doc_id] = record
            self._save_index()
            self._save_manifest()
            logger.info("Indexed %s: %d pages, %d chunks", filename, len(pages), len(chunks))
            return record, True

    def delete(self, document_id: str) -> bool:
        with self._lock:
            record = self._docs.pop(document_id, None)
            if record is None:
                return False
            if self._index is not None and record.chunk_ids:
                self._index.delete(record.chunk_ids)
            self.file_path(document_id).unlink(missing_ok=True)
            self._save_index()
            self._save_manifest()
            logger.info("Deleted %s (%s)", record.filename, document_id)
            return True
