"""Offline retrieval evaluation: a golden question set scored with recall@k and MRR.

Embeddings are served from a committed cache (backend/tests/eval/embeddings.npz), so the
eval runs in CI with no API key and no quota. Record or refresh the cache with:

    python -m backend.scripts.retrieval_eval --record
"""

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml
from langchain_core.embeddings import Embeddings

from backend.pdf import extract_pages
from backend.store import DocumentStore, SearchHit

EVAL_DIR = Path(__file__).resolve().parent / "tests" / "eval"
GOLDEN = EVAL_DIR / "golden.yaml"
CACHE = EVAL_DIR / "embeddings.npz"
SAMPLES = Path(__file__).resolve().parent.parent / "samples"


class MissingEmbedding(LookupError):
    pass


class CachedEmbeddings(Embeddings):
    """Embeddings looked up by sha256(model + text). With `inner`, misses are fetched and kept."""

    def __init__(self, model_id: str, path: Path = CACHE, inner: Embeddings | None = None):
        self.model_id, self.path, self.inner = model_id, path, inner
        self.vectors: dict[str, np.ndarray] = {}
        if path.exists():
            with np.load(path) as data:
                self.vectors = {k: data[k] for k in data.files}
        self.dirty = False

    def _key(self, text: str) -> str:
        return hashlib.sha256(f"{self.model_id}\n{text}".encode()).hexdigest()

    def _get(self, texts: list[str], fetch) -> list[list[float]]:
        keys = [self._key(t) for t in texts]
        missing = [t for t, k in zip(texts, keys, strict=True) if k not in self.vectors]
        if missing:
            if self.inner is None:
                raise MissingEmbedding(f"{len(missing)} texts not in {self.path.name}; run with --record")
            for text, vec in zip(missing, fetch(missing), strict=True):
                self.vectors[self._key(text)] = np.asarray(vec, dtype=np.float32)
            self.dirty = True
        return [self.vectors[k].tolist() for k in keys]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._get(texts, lambda m: self.inner.embed_documents(m))

    def embed_query(self, text: str) -> list[float]:
        # Query and document embeddings differ for some models (task types), so key them apart.
        return self._get([f"query: {text}"], lambda m: [self._throttled_query(x[7:]) for x in m])[0]

    def _throttled_query(self, text: str) -> list[float]:
        time.sleep(0.7)  # free tiers cap embeddings at ~100/minute; recording is a one-off
        return self.inner.embed_query(text)

    def save(self) -> None:
        if self.dirty:
            np.savez_compressed(self.path, **self.vectors)
            self.dirty = False


@dataclass
class Metrics:
    recall_at_1: float
    recall_at_3: float
    recall_at_6: float
    mrr: float
    page_accuracy: float  # of found answers, the cited page range contains the clause's page
    negative_top_score: float  # highest similarity for an out-of-scope question (lower is better)

    def row(self, name: str) -> str:
        return (
            f"{name:<8} R@1 {self.recall_at_1:.2f}  R@3 {self.recall_at_3:.2f}  R@6 {self.recall_at_6:.2f}  "
            f"MRR {self.mrr:.2f}  page {self.page_accuracy:.2f}  neg-max {self.negative_top_score:.3f}"
        )


def load_golden() -> list[dict]:
    return yaml.safe_load(GOLDEN.read_text())


def build_store(tmp_dir: Path, embeddings: Embeddings) -> DocumentStore:
    store = DocumentStore(tmp_dir, embeddings, embedding_id="eval")
    for pdf in sorted(SAMPLES.glob("*.pdf")):
        data = pdf.read_bytes()
        store.add(pdf.name, data, extract_pages(data))
    return store


def _matches(hit: SearchHit, expected: str) -> bool:
    prefix, clause = expected.split(":")
    return hit.filename.startswith(prefix) and clause in (hit.clauses or {})


def evaluate(store: DocumentStore, golden: list[dict], strategy: str = "hybrid", k: int = 6) -> Metrics:
    positives = [g for g in golden if g["expect"]]
    negatives = [g for g in golden if not g["expect"]]
    hits_at = {1: 0, 3: 0, 6: 0}
    rr_total, page_ok, found = 0.0, 0, 0
    for item in positives:
        hits = store.search(item["q"], k=k, strategy=strategy)
        rank = next((i for i, h in enumerate(hits, 1) if any(_matches(h, e) for e in item["expect"])), None)
        if rank is None:
            continue
        for cutoff in hits_at:
            hits_at[cutoff] += rank <= cutoff
        rr_total += 1 / rank
        found += 1
        hit = hits[rank - 1]
        clause = next(e.split(":")[1] for e in item["expect"] if _matches(hit, e))
        first, last = hit.clauses[clause]
        page_ok += hit.page <= first and last <= (hit.page_end or hit.page)
    negative_scores = [
        max((h.score for h in store.search(g["q"], k=k, strategy=strategy)), default=0.0) for g in negatives
    ]
    n = len(positives)
    return Metrics(
        recall_at_1=hits_at[1] / n,
        recall_at_3=hits_at[3] / n,
        recall_at_6=hits_at[6] / n,
        mrr=rr_total / n,
        page_accuracy=page_ok / found if found else 0.0,
        negative_top_score=max(negative_scores, default=0.0),
    )
