"""Keyword (BM25) retrieval and rank fusion, used alongside the FAISS vector index.

Embeddings miss exact terms ("CPNI", "STIR/SHAKEN", clause numbers); BM25 catches them.
The two ranked lists are merged with reciprocal-rank fusion, which needs no score
calibration. Nothing here calls an AI provider.
"""

import logging
import re
from dataclasses import dataclass

import bm25s
import numpy as np
import Stemmer

logging.getLogger("bm25s").setLevel(logging.WARNING)

RRF_K = 60
CANDIDATES = 20  # taken from each retriever before fusion

_stemmer = Stemmer.Stemmer("english")
# A clause number only counts as a reference with an explicit cue ("clause 3.2", "§7.2",
# "what does 3.2 say"), so "version 2.5" or "$1.50" don't steer retrieval.
_CLAUSE_REF = re.compile(
    r"(?:§|\bclause|\bsection|\barticle|\bpara(?:graph)?)\s*(\d{1,2}(?:\.\d{1,2})+)\b"
    r"|\b(\d{1,2}(?:\.\d{1,2})+)\s+(?:say|says|state|states|require|requires|mean|cover|covers)\b",
    re.IGNORECASE,
)
_SECTION_REF = re.compile(r"(?:§|\bsection|\bclause)\s*(\d{1,2})(?![.\d])", re.IGNORECASE)
CLAUSE_BOOST = 0.05  # RRF scores top out near 0.033, so this outranks without swamping relevance
SECTION_BOOST = 0.02


def _tokens(texts: list[str]) -> list[list[str]]:
    return bm25s.tokenize(texts, stopwords="en", stemmer=_stemmer, return_ids=False, show_progress=False)


@dataclass(frozen=True)
class Entry:
    chunk_id: str
    document_id: str
    text: str  # search text: context line + passage


class KeywordIndex:
    """An in-memory BM25 index, rebuilt from the vector store's chunks (milliseconds)."""

    def __init__(self, entries: list[Entry]):
        self.entries = entries
        self._retriever: bm25s.BM25 | None = None
        if entries:
            retriever = bm25s.BM25()
            retriever.index(_tokens([e.text for e in entries]), show_progress=False)
            self._retriever = retriever

    def search(self, query: str, k: int = CANDIDATES, allowed: set[str] | None = None) -> list[str]:
        if self._retriever is None:
            return []
        query_tokens = _tokens([query])
        vocab = self._retriever.vocab_dict
        if not any(t in vocab for t in query_tokens[0]):
            return []
        mask = None
        if allowed is not None:
            mask = np.array([1.0 if e.document_id in allowed else 0.0 for e in self.entries], dtype=np.float32)
            if not mask.any():
                return []
        k = min(k, len(self.entries))
        ids, scores = self._retriever.retrieve(query_tokens, k=k, weight_mask=mask, show_progress=False)
        return [self.entries[i].chunk_id for i, s in zip(ids[0], scores[0], strict=True) if s > 0]


def fuse(*rankings: list[str], k: int = RRF_K) -> dict[str, float]:
    """Reciprocal-rank fusion: score = sum over lists of 1 / (k + rank)."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return scores


def clause_refs(query: str) -> list[str]:
    return [a or b for a, b in _CLAUSE_REF.findall(query)]


def reference_boost(query: str, metadata: dict) -> float:
    """Prefer chunks containing a clause or section the question explicitly names."""
    clauses = metadata.get("clauses") or {}
    boost = sum(CLAUSE_BOOST for ref in clause_refs(query) if ref in clauses)
    boost += sum(SECTION_BOOST for sec in _SECTION_REF.findall(query) if metadata.get("section") == str(int(sec)))
    return boost
