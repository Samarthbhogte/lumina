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
                         └──▶ RAG: retrieve top-k page chunks ──▶ Gemini or OpenAI chat model
```

1. **Ingest.** PyMuPDF extracts text page by page. Each page is split into about 1,000-character
   chunks tagged with `document_id`, `filename` and `page`. The chunks are embedded
   (`gemini-embedding-001` or `text-embedding-3-small`) and stored in one shared FAISS index.
   If you switch provider, existing documents are re-embedded from the stored PDFs on startup.
2. **Ask.** The question (condensed with chat history if needed) retrieves the top 6
   chunks. These go to the model as numbered `<source>` blocks with instructions to cite
   them and to refuse when they don't contain the answer.
3. **Answer.** The API streams `sources`, then `token` events, then a `done` event with
   which sources were cited, `found`, and a confidence level based on retrieval
   similarity.

## Quick start

Requirements: Python 3.12, Node 22, and an API key for **Gemini** (free tier: get one at
https://aistudio.google.com/apikey) or **OpenAI**.

```bash
# 1. Backend
cp backend/.env.example backend/.env        # set LUMINA_PROVIDER and that provider's key
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
backend/.venv/bin/python -m pytest -q                 # 72 offline tests, fake models, no cost
backend/.venv/bin/ruff check backend
cd frontend && npm run lint && npm run typecheck && npm run build
npx promptfoo@latest eval -c promptfoo-tests/promptfooconfig.yaml   # live evals, see promptfoo-tests/
```

CI (`.github/workflows/ci.yml`) runs lint, tests, the build, `pip-audit` and `npm audit`.

## Configuration

Set these in `backend/.env` or the environment.

| Variable | Default | |
| --- | --- | --- |
| `LUMINA_PROVIDER` | `openai` | `gemini` or `openai` |
| `GOOGLE_API_KEY` (or `GEMINI_API_KEY`) | (none) | Needed when the provider is `gemini` |
| `OPENAI_API_KEY` | (none) | Needed when the provider is `openai` |
| `LUMINA_CHAT_MODEL` | per provider | `gemini-2.5-flash` / `gpt-4o-mini` |
| `LUMINA_FALLBACK_MODELS` | per provider | Gemini: `gemini-3.5-flash-lite,gemini-3.1-flash-lite`. Tried in order when the chat model is out of quota |
| `LUMINA_EMBEDDING_MODEL` | per provider | `gemini-embedding-001` / `text-embedding-3-small`. Changing it re-indexes on startup |
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
  the API can upload, delete, and use up your provider quota. Accounts and per-user
  workspaces are the natural next step.
- **One process owns `data/`.** Run a single uvicorn worker, and add files through the API
  (the ingest script does).
- **Scanned PDFs** without a text layer are rejected. OCR isn't included.
- **Gemini free tier:** Google may use free-tier prompts and content to improve its
  products. Don't upload confidential policies on the free tier. Use a paid key or OpenAI
  for those.
- **Free-tier daily limits.** Each Gemini model allows a small number of requests per day
  (20 for `gemini-2.5-flash` at the time of writing). A follow-up question uses two. When a
  model's quota runs out, Lumina automatically falls back to `gemini-3.5-flash-lite`, then
  `gemini-3.1-flash-lite` (set `LUMINA_FALLBACK_MODELS`, or `none` to disable). Once all are
  used up, the UI says when the limit resets.
- Confidence comes from retrieval similarity, not from verifying the answer. Check the
  cited page for anything that matters.

## Layout

```
backend/    FastAPI app: main.py (app factory), api.py (routes), store.py, rag.py, providers.py, pdf.py, guard.py
  tests/    pytest suite      scripts/  ingest_folder.py, finetune/ (earlier experiments)
frontend/   Next.js app: src/components/Workspace.tsx is the main screen
samples/    five simulated policy PDFs for trying it out
promptfoo-tests/   live grounded-answer evals
notebooks/  original LangChain / LangGraph exploration
```
