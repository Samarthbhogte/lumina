"""Index every PDF in a folder, e.g. the bundled samples:

    python -m backend.scripts.ingest_folder backend/data/testing_pdfs

Run from the repository root with OPENAI_API_KEY set. Already-indexed files are skipped.
"""

import argparse
import sys
from pathlib import Path

from langchain_openai import OpenAIEmbeddings

from backend.config import get_settings
from backend.pdf import PDFError, extract_pages
from backend.store import DocumentStore


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("folder", type=Path)
    args = parser.parse_args()

    settings = get_settings()
    if not settings.openai_api_key:
        print("OPENAI_API_KEY is not set.", file=sys.stderr)
        return 1
    store = DocumentStore(
        settings.data_dir,
        OpenAIEmbeddings(model=settings.embedding_model, api_key=settings.openai_api_key),
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
    )
    pdfs = sorted(args.folder.glob("*.pdf"))
    if not pdfs:
        print(f"No PDFs in {args.folder}")
        return 1
    for path in pdfs:
        data = path.read_bytes()
        try:
            record, created = store.add(path.name, data, extract_pages(data, settings.max_pages))
        except PDFError as exc:
            print(f"skip   {path.name}: {exc}")
            continue
        print(f"{'added' if created else 'exists'} {path.name}: {record.pages} pages, {record.chunks} chunks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
