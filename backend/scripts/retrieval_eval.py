"""Score retrieval on the golden set and compare dense, keyword and hybrid search.

python -m backend.scripts.retrieval_eval            # offline, from the committed cache
python -m backend.scripts.retrieval_eval --record   # fetch missing embeddings (uses API quota)
"""

import argparse
import sys
import tempfile
from pathlib import Path

from backend.config import get_settings
from backend.evalkit import CachedEmbeddings, MissingEmbedding, build_store, evaluate, load_golden
from backend.providers import build_models


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--record", action="store_true", help="fetch and cache missing embeddings")
    args = parser.parse_args()

    settings = get_settings()
    inner = None
    if args.record:
        inner, _ = build_models(settings)
        if inner is None:
            print(f"{settings.api_key_name} is not set.", file=sys.stderr)
            return 1
    cache = CachedEmbeddings(settings.embedding_id, inner=inner)
    golden = load_golden()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            store = build_store(Path(tmp), cache)
            print(f"{len(golden)} questions, embeddings: {settings.embedding_id}")
            for strategy in ("dense", "keyword", "hybrid"):
                print(evaluate(store, golden, strategy).row(strategy))
    except MissingEmbedding as exc:
        print(exc, file=sys.stderr)
        return 1
    finally:
        cache.save()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
