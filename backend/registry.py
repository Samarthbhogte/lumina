"""One DocumentStore per workspace, opened on demand and kept in a small LRU.

Each workspace owns data_dir/workspaces/<id>/ (index, manifest, PDFs). A store in use by a
request (an upload, a streaming answer) is reference-counted and never evicted mid-use.
Stores save to disk on every change, so evicting an idle one is just forgetting it.
"""

import threading
from collections import OrderedDict
from contextlib import contextmanager
from pathlib import Path

from langchain_core.embeddings import Embeddings

from backend.config import Settings
from backend.store import DocumentStore


class StoreRegistry:
    def __init__(self, settings: Settings, embeddings: Embeddings, embedding_id: str):
        self.settings = settings
        self.embeddings = embeddings
        self.embedding_id = embedding_id
        self._open: OrderedDict[str, DocumentStore] = OrderedDict()
        self._in_use: dict[str, int] = {}
        self._lock = threading.Lock()
        self._opening: dict[str, threading.Lock] = {}

    def path(self, workspace_id: str) -> Path:
        return self.settings.data_dir / "workspaces" / workspace_id

    def _open_store(self, workspace_id: str) -> DocumentStore:
        return DocumentStore(
            self.path(workspace_id),
            self.embeddings,
            embedding_id=self.embedding_id,
            chunk_size=self.settings.chunk_size,
            chunk_overlap=self.settings.chunk_overlap,
            max_chunks=self.settings.max_chunks_per_document,
        )

    def _evict(self) -> None:
        for wid in list(self._open):
            if len(self._open) <= self.settings.max_open_stores:
                return
            if not self._in_use.get(wid):
                del self._open[wid]

    @contextmanager
    def use(self, workspace_id: str):
        """Borrow the workspace's store for the duration of a request."""
        with self._lock:
            opener = self._opening.setdefault(workspace_id, threading.Lock())
        with opener:  # one thread opens a given store; others wait for it
            with self._lock:
                store = self._open.get(workspace_id)
            if store is None:
                store = self._open_store(workspace_id)
            with self._lock:
                store = self._open.setdefault(workspace_id, store)
                self._open.move_to_end(workspace_id)
                self._in_use[workspace_id] = self._in_use.get(workspace_id, 0) + 1
                self._evict()
        try:
            yield store
        finally:
            with self._lock:
                self._in_use[workspace_id] -= 1

    def forget(self, workspace_id: str) -> None:
        with self._lock:
            self._open.pop(workspace_id, None)
