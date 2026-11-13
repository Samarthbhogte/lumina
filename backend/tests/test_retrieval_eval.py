"""Retrieval regression floors on the golden set, using cached real embeddings (no API calls).

Refresh the cache after changing chunking or the embedding model:
    python -m backend.scripts.retrieval_eval --record
"""

import pytest

from backend.evalkit import CACHE, CachedEmbeddings, MissingEmbedding, build_store, evaluate, load_golden

EMBEDDING_ID = "gemini:gemini-embedding-001"  # the model the committed cache was recorded with


@pytest.fixture(scope="module")
def golden_store(tmp_path_factory):
    if not CACHE.exists():
        pytest.skip("no embedding cache; run python -m backend.scripts.retrieval_eval --record")
    try:
        return build_store(tmp_path_factory.mktemp("eval"), CachedEmbeddings(EMBEDDING_ID))
    except MissingEmbedding as exc:
        pytest.skip(f"embedding cache is stale: {exc}")


@pytest.mark.parametrize("strategy", ["hybrid", "dense"])
def test_retrieval_meets_floors(golden_store, strategy):
    try:
        m = evaluate(golden_store, load_golden(), strategy)
    except MissingEmbedding as exc:
        pytest.skip(f"embedding cache is stale: {exc}")
    assert m.recall_at_6 >= 0.95, m
    assert m.recall_at_1 >= 0.90, m
    assert m.mrr >= 0.90, m
    assert m.page_accuracy >= 0.95, m


def test_out_of_scope_questions_stay_below_medium_confidence(golden_store):
    from backend.config import DEFAULTS

    m = evaluate(golden_store, load_golden(), "hybrid")
    assert m.negative_top_score < DEFAULTS["gemini"]["confidence_medium"], m
