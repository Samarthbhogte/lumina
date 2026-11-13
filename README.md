# Lumina

Ask questions about your policy and regulatory PDFs and get answers that cite the exact
document, clause and page. You can export them as audit-ready evidence and check a policy
against a regulation clause by clause.

## Features

- **Clause-level citations.** Every claim carries a `[n]` marker labelled like
  "GDPR Sample Compliance §7.2, pp.1–2". Click it to see the passage and open the PDF at that page.
  Labels come from the document's numbering, never from the model.
- **Better retrieval.** Documents are chunked by numbered section, so clauses that run over a
  page break stay whole. Keyword search (BM25 with stemming) is fused with semantic search.
  Naming a clause ("what does 3.2 say") retrieves it directly.
- **Accounts and workspaces.** Invite-only sign-in; the first user becomes admin. Each person
  has a personal workspace and can create team workspaces with owner, editor and viewer roles,
  using copyable invite links. Non-members can't see that a workspace exists.
- **Saved chats.** Conversations are stored on the server. Follow-ups are understood in context.
- **Evidence packs.** Download any answer, or a whole chat, as a PDF. Each pack has the
  question, the answer, the cited passages in full, the document hashes and versions, the model
  used and a disclaimer. Its canonical data is embedded with a SHA-256 hash, so edits are
  detectable (`POST /api/evidence/verify` or `scripts/verify_evidence.py`).
- **Gap check.** Check which requirements of one document (say, a regulation) another
  document (your policy) addresses. Statuses are *Addressed*, *Partially addressed*,
  *No matching passage* and *Needs review*, never a "compliant" verdict. Every quote is checked
  word for word against the passage. A 40-clause regulation takes about 3 AI requests, the
  cost is estimated first, and a run stopped by quota can be resumed.
- **Scanned PDFs.** Pages with no text layer are read with local OCR (Tesseract). OCR'd text
  is labelled, and its confidence is capped.
- **Honest uncertainty.** When the documents don't contain the answer, Lumina says so. The
  confidence badge shows how closely the cited passages match the question.
- **Guardrails.** Prompt injection is screened, and document text is treated as data.
  Answers can't load images, and a CSP is set. Sessions use HttpOnly cookies with CSRF checks,
  login attempts are throttled, every user has a daily AI quota, and an audit log records
  security-relevant events.

## How it works

```
Browser ──▶ Next.js 16 (UI + /api proxy, one origin) ──▶ FastAPI
                                                         ├─ SQLite: users, workspaces, sessions, chats, answers, audit
                                                         ├─ per-workspace DocumentStore: FAISS + BM25 + PDFs
                                                         └─ Gemini or OpenAI (chat with fallbacks, embeddings)
```

1. **Ingest.** PyMuPDF extracts page text, using OCR for scans. The chunker splits documents
   into numbered sections and clauses, keeping a clause-to-page map. It guards against
   tables of contents, page headers and footers, and stray numbers. Chunks are embedded
   with their document and section context.
2. **Ask.** A follow-up is first rewritten into a standalone query using the stored
   conversation. Semantic and keyword results are fused, and each section is returned
   at most once. The top passages go to the model as numbered `<source>` blocks.
3. **Answer.** Answers stream over SSE. The server picks the cited clause, assesses
   confidence and stores the answer, which is what evidence exports are built from.

## Quick start

Requirements: Python 3.12, Node 22, and an API key for **Gemini** (free tier at
https://aistudio.google.com/apikey) or **OpenAI**. For scanned PDFs, Tesseract is optional
(`brew install tesseract`).

```bash
# 1. Backend
cp backend/.env.example backend/.env        # set LUMINA_PROVIDER and that provider's key
python3.12 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements-dev.txt
backend/.venv/bin/uvicorn backend.main:app --reload --port 8000

# 2. Frontend (new terminal)
cd frontend && npm install && npm run dev
```

Open http://localhost:3000. The first visit shows **Create the admin account**. That account
adopts any library left from Lumina v2, after a backup is taken.

To load the five sample policies into your personal workspace:

```bash
backend/.venv/bin/python -m backend.scripts.ingest_folder samples --email you@example.com
```

**No key? Use demo mode.** `backend/.venv/bin/uvicorn backend.devserver:app --port 8000` runs
the real API with fake embeddings and a scripted model, free and offline.

**Docker:** `docker compose up --build` (or `LUMINA_WEB_PORT=3100 docker compose up --build`
if port 3000 is taken), then open the web port. This includes Tesseract, reads `backend/.env`,
keeps data in a named volume, and doesn't publish the API, so only the web app is reachable.

## Tests and evals

```bash
backend/.venv/bin/python -m pytest -q                       # 130 offline tests (fake models, no cost)
backend/.venv/bin/python -m backend.scripts.retrieval_eval  # golden-set retrieval: dense vs keyword vs hybrid
cd frontend && npm run lint && npm run typecheck && npm run build
npx promptfoo@latest eval -c promptfoo-tests/promptfooconfig.yaml   # 11 live checks (uses your AI quota)
```

The retrieval eval scores 40 questions over the samples, using cached real embeddings, so
it needs no API calls. Current results are recall@1 1.00 and MRR 1.00. The set is small,
in-sample and written by the developer, so treat it as a regression floor, not a benchmark.
CI runs lint, tests, the build, `pip-audit` and `npm audit`.

## Configuration

Set these in `backend/.env` or the environment.

| Variable | Default | |
| --- | --- | --- |
| `LUMINA_PROVIDER` | `openai` | `gemini` or `openai` |
| `GOOGLE_API_KEY` / `OPENAI_API_KEY` | (none) | Key for the chosen provider |
| `LUMINA_CHAT_MODEL` | per provider | `gemini-2.5-flash` / `gpt-4o-mini` |
| `LUMINA_FALLBACK_MODELS` | per provider | Gemini: `gemini-3.5-flash-lite,gemini-3.1-flash-lite`, used when out of quota |
| `LUMINA_EMBEDDING_MODEL` | per provider | Changing it re-indexes on startup |
| `LUMINA_SIGNUP` | `invite` | `open` lets anyone create an account |
| `LUMINA_COOKIE_SECURE` | `false` | Set `true` behind HTTPS |
| `LUMINA_TRUSTED_ORIGINS` | `http://localhost:3000` | Browser origins allowed to make changes |
| `LUMINA_DAILY_QUESTIONS_PER_USER` / `_TOTAL` | `25` / `55` | AI questions per day (reset at midnight Pacific) |
| `LUMINA_OCR` | `auto` | `off` to never OCR scanned pages |
| `LUMINA_DATA_DIR` | `./data` | SQLite database plus one folder per workspace |
| `LUMINA_MAX_UPLOAD_MB` / `LUMINA_MAX_FILES_PER_UPLOAD` | `25` / `10` | |
| `LUMINA_ENABLE_DOCS` | `true` | Swagger UI at `/docs` |

The browser only talks to Next.js, which proxies `/api/*` to FastAPI. Set the target with
`LUMINA_API_INTERNAL_URL` (default `http://127.0.0.1:8000`), which is read at build time.

## API (all under `/api`; state changes need the `X-Lumina-CSRF: 1` header)

| Area | Routes |
| --- | --- |
| Accounts | `GET auth/setup`, `POST auth/signup`, `auth/login`, `auth/logout`, `auth/password`, `auth/reset`; `GET auth/me`, `auth/sessions` |
| Workspaces | `GET/POST workspaces`; `PATCH/DELETE workspaces/{ws}`; `GET/PATCH/DELETE …/members/{user}`; `GET/POST/DELETE …/invites`; `GET invites/{token}`, `POST invites/{token}/accept` |
| Documents | `GET/POST workspaces/{ws}/documents`; `DELETE …/documents/{id}`; `GET …/documents/{id}/file`; `GET …/documents/history` |
| Questions | `POST workspaces/{ws}/ask` and `…/ask/stream` with `{question, conversation_id?, document_ids?}`; `GET/DELETE …/conversations[/{id}]` |
| Evidence | `GET …/answers/{id}/export`, `GET …/conversations/{id}/export`, `POST evidence/verify` |
| Gap check | `POST …/comparisons/estimate`, `POST …/comparisons`, `POST …/comparisons/{id}/resume`, `GET …/comparisons[/{id}]` |

## Limits

- **Put a reverse proxy in front for real deployments.** Next.js's `/api` proxy doesn't pass
  the browser's IP on, so in Docker every request reaches the API from the web container.
  Per-IP login throttling then treats all users as one. Caddy or nginx in front of the web
  container, setting `X-Forwarded-For` and handling HTTPS, fixes this, and the API already
  trusts that header from the compose network.
- **Self-hosted, small teams.** There's no email: invite and password-reset links are
  copied by hand. There's no SSO or billing. Run one uvicorn worker, because one process
  owns `data/`.
- **Gemini free tier.** Google may use free-tier content to improve its products, so don't
  upload confidential policies there; use a paid key or OpenAI instead. Daily limits are small
  (20 requests per model). Lumina falls back to other free models, then says when the limit
  resets.
- **Confidence measures retrieval similarity**, not legal correctness. A gap check can miss a
  passage, which is why its status reads "No matching passage" rather than "Missing". Always
  check the cited page.

## Layout

```
backend/    main.py (app), api.py, account_api.py, compare_api.py, auth.py, db.py, quota.py,
            store.py, registry.py, chunking.py, hybrid.py, citations.py, rag.py, evidence.py,
            compare.py, pdf.py, providers.py, guard.py, migrate.py
  tests/    pytest suite (+ eval/ golden set and embedding cache)
  scripts/  ingest_folder, retrieval_eval, verify_evidence, finetune/ (earlier experiments)
frontend/   Next.js: app/ (login, invite, reset, w/[wsId]), components/
docs/       PRODUCT-BRIEF.md, V3-PLAN.md
samples/    five simulated policy PDFs
promptfoo-tests/   live grounded-answer evals
```
