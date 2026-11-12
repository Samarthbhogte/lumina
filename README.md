# Lumina

Ask questions about your policy and regulatory PDFs and get answers that cite the exact
document and page. Upload GDPR, HIPAA, telecom or internal policies; Lumina retrieves the
relevant passages, answers from them only, and links every claim to its source.

## Features

- **Cited answers.** Every claim carries a `[n]` marker. Click it to see the passage and
  open the PDF at that page.
- **Streaming chat with follow-ups.** Answers stream token by token. A follow-up like "and
  how long is it?" is rewritten into a standalone search using the conversation.
- **Document library.** Drag-and-drop upload, duplicate detection, delete, and "search only
  these documents".
- **Honest uncertainty.** If the documents don't answer the question, Lumina says so. A
  badge shows how closely the cited passages match the question.
- **Guardrails.** It screens prompt injection in questions and history, and treats document
  text as untrusted data. Answers can't load images. It enforces upload size, page and
  chunk limits.
- **Light and dark themes**, a responsive layout down to phone width, and keyboard and
  screen-reader support.

## How it works

```
Next.js 16 UI ──SSE──▶ FastAPI ──▶ DocumentStore (FAISS + manifest + original PDFs)
                         │                     ▲
                         └──▶ RAG: retrieve top-k page chunks ──▶ OpenAI chat model
```

1. **Ingest.** PyMuPDF extracts text page by page. Each page is split into about 1,000-character
   chunks tagged with `document_id`, `filename` and `page`. The chunks are embedded with
   `text-embedding-3-small` and stored in one shared FAISS index.
2. **Ask.** The question (condensed with chat history if needed) retrieves the top 6
   chunks. These go to the model as numbered `<source>` blocks with instructions to cite
   them and to refuse when they don't contain the answer.
3. **Answer.** The API streams `sources`, then `token` events, then a `done` event with
   which sources were cited, `found`, and a confidence level based on retrieval
   similarity.

## Quick start

Requirements: Python 3.12, Node 22, and an OpenAI API key.

```bash
# 1. Backend
cp backend/.env.example backend/.env        # then put your OPENAI_API_KEY in it
python3.12 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements-dev.txt
backend/.venv/bin/uvicorn backend.main:app --reload --port 8000

# 2. Frontend (new terminal)
cd frontend && cp .env.example .env.local && npm install && npm run dev

# 3. Optional: load the five sample policies
backend/.venv/bin/python -m backend.scripts.ingest_folder samples
```

Open http://localhost:3000.

**No key? Use demo mode.** `backend/.venv/bin/uvicorn backend.devserver:app --port 8000`
runs the real API with fake embeddings and a scripted model. It's free and works offline,
which is good for UI work. Retrieval isn't semantic in this mode.

**Docker:** `docker compose up --build`. This reads `backend/.env` and keeps data in a
named volume.

## Tests and evals

```bash
backend/.venv/bin/python -m pytest -q                 # 56 offline tests, fake models, no cost
backend/.venv/bin/ruff check backend
cd frontend && npm run lint && npm run typecheck && npm run build
npx promptfoo@latest eval -c promptfoo-tests/promptfooconfig.yaml   # live evals, see promptfoo-tests/
```

CI (`.github/workflows/ci.yml`) runs lint, tests, the build, `pip-audit` and `npm audit`.

## Configuration

Set these in `backend/.env` or the environment.

| Variable | Default | |
| --- | --- | --- |
| `OPENAI_API_KEY` | (none) | Required for uploads and questions |
| `LUMINA_CHAT_MODEL` | `gpt-4o-mini` | Any OpenAI chat model |
| `LUMINA_EMBEDDING_MODEL` | `text-embedding-3-small` | Changing it needs a re-index |
| `LUMINA_CORS_ORIGINS` | `http://localhost:3000` | Comma-separated, no `*` |
| `LUMINA_DATA_DIR` | `./data` | Index, manifest and stored PDFs |
| `LUMINA_MAX_UPLOAD_MB` / `LUMINA_MAX_FILES_PER_UPLOAD` | `25` / `10` | |
| `LUMINA_TOP_K` | `6` | Passages retrieved per question |
| `LUMINA_ENABLE_DOCS` | `true` | Swagger UI at `/docs` |

The frontend reads `NEXT_PUBLIC_API_URL` (default `http://localhost:8000`).

## API

| Method | Path | |
| --- | --- | --- |
| `GET` | `/api/health` | Status, model, document and chunk counts |
| `GET` | `/api/documents` | List documents |
| `POST` | `/api/documents` | Upload PDFs (multipart field `files`) |
| `DELETE` | `/api/documents/{id}` | Remove a document and its chunks |
| `GET` | `/api/documents/{id}/file` | The original PDF (add `#page=N` in a browser) |
| `POST` | `/api/ask` | `{question, history?, document_ids?}` → answer JSON |
| `POST` | `/api/ask/stream` | Same input, server-sent events |

## Limits and next steps

- **No authentication.** Run it on your machine or a trusted network. Anyone who can reach
  the API can upload, delete, and spend your OpenAI budget. Accounts and per-user
  workspaces are the natural next step.
- **One process owns `data/`.** Run a single uvicorn worker, and add files through the API
  (the ingest script does).
- **Scanned PDFs** without a text layer are rejected. OCR isn't included.
- Confidence comes from retrieval similarity, not from verifying the answer. Check the
  cited page for anything that matters.

## Layout

```
backend/    FastAPI app: main.py (app factory), api.py (routes), store.py, rag.py, pdf.py, guard.py
  tests/    pytest suite      scripts/  ingest_folder.py, finetune/ (earlier experiments)
frontend/   Next.js app: src/components/Workspace.tsx is the main screen
samples/    five simulated policy PDFs for trying it out
promptfoo-tests/   live grounded-answer evals
notebooks/  original LangChain / LangGraph exploration
```
