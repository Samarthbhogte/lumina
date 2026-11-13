# Lumina v3: plan

**Status:** proposed, awaiting approval.
**Inputs:** [PRODUCT-BRIEF.md](PRODUCT-BRIEF.md) (ECC product-lens), plus design reviews from the
RAG Pipeline Engineer, Identity & Access Engineer and Compliance Auditor agents.

**Thesis.** A reviewer can verify any answer in under 30 seconds, and can hand an auditor an
evidence pack without editing it.

**Hard constraints:**

- Gemini free tier, roughly 20 chat requests per day per model, so:
  - no LLM calls for re-ranking, query expansion or HyDE;
  - every multi-call job is budgeted.
- Local and CPU-only: no torch, no paid SaaS.
- One uvicorn worker owns the data directory.

---

## Phase 0. Spike: same-origin proxy (½ day, go/no-go)

Accounts need the browser to call `/api` on the Next.js origin, proxied to FastAPI, so that
session cookies reach SSE streams and PDF links.

- **Prove:** SSE streams token by token through a Next 16 rewrite, and a 25 MB multipart upload passes.
- **Fallback:** a small Caddy reverse proxy in front of both.

**Exit:** a recorded streaming test and an upload test through `localhost:3000/api`.

## Phase 1. Smarter answers (retrieval foundation)

**ECC:** `/orch-add-feature` per step and `ecc:eval-harness`.
**Review:** `rag-pipeline-reviewer` agent.

1. **Offline golden-set eval first.**
   - `backend/tests/golden.yaml` has about 35 questions, each with the expected file,
     section, clause and page.
   - Coverage includes cross-page clauses, "what does 3.2 say" questions, two-document
     questions, and 6 negatives.
   - Reports recall@1/3/6, MRR, page accuracy and negative scores as regression floors.
   - Embeddings come from a committed `CachedEmbeddings` npz cache. Recording it costs about
     36 embedding calls once; after that it's free, with 0 chat calls.
2. **Structure-aware chunking.**
   - Chunk the whole document by section and clause headings, with monotonic-number guards and
     the current splitter as a fallback.
   - **Why:** today every sample has a clause split across pages 1 and 2.
   - **Metadata:** `section`, `heading`, a clause→page map, and `page_end`. Chunk text is
     prefixed with "Doc > 7. Breach Notification".
   - **Re-index:** a chunker version goes into `embedding_id` so stored PDFs re-index.
3. **Hybrid search.**
   - `bm25s` + `PyStemmer` keyword search (about 1.5 MB), fused with the FAISS results by
     reciprocal-rank fusion (k=60), with a boost when the query names a clause number.
   - The keyword index is built in memory per store; nothing new is pickled.
   - `SearchHit.score` stays cosine, because confidence depends on it.
4. **Dedupe and diversity:** at most one hit per (document, section), at most 3 hits per document.
5. **Clause-level citations.**
   - The server builds labels such as "GDPR Sample §7.2, p.1". The model never writes § numbers.
   - New `Source` fields: `section`, `heading`, `clause`, `page_end`, `label`.
   - The UI shows the label on chips and cards.
6. **Re-calibrate** the confidence thresholds on the new chunks. Add promptfoo checks for the
   § label, the cross-page clause, "clause 3.2", two-document breach, and an invented section.
7. **Re-ranker (optional):** a `fastembed` cross-encoder behind `LUMINA_RERANK`, added
   **only if** precision@3 is below 0.8 after steps 2–4.

**Exit:** recall@6 ≥ 0.90, MRR ≥ 0.80, and § labels on ≥ 80% of the golden answers.

## Phase 2. Accounts & workspaces

**ECC:** `/orch-add-feature`, `ecc:security-review`, `ecc:tdd-workflow`.
**Review:** Identity & Access Engineer and Security Architect agents.

**Database and auth:**

- **App database:** SQLite (WAL) with SQLAlchemy 2.1 and Alembic. Tables: `users`,
  `workspaces`, `memberships` (owner/editor/viewer), `invites`, `sessions`, `conversations`,
  `messages`, `usage`, `audit_events`.
- **Passwords:** argon2id via `argon2-cffi`.
- **Sessions:** opaque server-side tokens in an `HttpOnly SameSite=Lax` cookie; only the
  SHA-256 is stored. 7 days idle, 30 days absolute, rotated at login.
- **Signup:** invite-only by default (`LUMINA_SIGNUP=invite|open`). The first user becomes admin.
- **Passwords and resets:** NIST 800-63B rules (≥ 15 characters, common-password list).
  Resets work by owner-generated link or CLI, since there's no email.

**Workspaces:**

- Routes move under `/api/workspaces/{ws}/…`.
- `require_member(role)` returns **404 to non-members**.
- A `StoreRegistry` keeps an LRU of per-workspace `DocumentStore`s, reference-counted so a
  store isn't dropped mid-stream.

**Security controls:**

- **CSRF:** SameSite cookie, Origin allowlist, and an `X-Lumina-CSRF` header.
- **Logins:** rate limited per account and per IP. Error messages and timing don't reveal
  whether an account exists.
- **Quota:** an atomic per-user daily reservation plus a global daily budget, aligned to
  Google's reset at midnight Pacific; one stream in flight per user.

**Conversations:**

- Stored on the server.
- The ask payload becomes `{conversation_id, question}`. The server rebuilds history from
  stored messages and **stops trusting client-sent history**, which closes an injection path.

**Frontend:**

- `/login`, `/invite/[token]` and `/w/[wsId]` pages.
- A workspace switcher and conversation list.
- A 401 redirects to login.
- The old localStorage chat is imported once, then cleared.

**Migration:** back up `data/` first. The existing library moves into the first admin's
personal workspace, with a CLI to do it explicitly.

**Exit:**

- A role × route authorisation test matrix.
- Cross-workspace document ids return 404 on file, ask and filter.
- CSRF, session and quota concurrency tests.
- A migration test against a copy of the v2 data layout.

## Phase 3. Evidence & audit trail

**ECC:** `/orch-add-feature`.
**Review:** Compliance Auditor agent.

1. **Answer records.**
   - Each recorded answer stores the question, the standalone search query, the answer, the
     full cited excerpts (not 400-character snippets) and the uncited retrievals.
   - It also stores `found` and confidence with their thresholds, the provider, **the model
     that actually answered** (fallbacks included) and the embedding model.
   - Plus the user, workspace, UTC timestamp, and each document's sha256 and version.
2. **Document version log.** A workspace's audit events record who uploaded, replaced or
   deleted which hash, and when, so a pack can show the version in force on a given date.
3. **Evidence pack export.**
   - `GET …/answers/{id}/export`, plus whole-conversation export.
   - A PDF built with the PyMuPDF `Story` API, which adds no new dependency.
   - Canonical JSON is embedded in the PDF, with a SHA-256 integrity hash and a disclaimer
     that can't be removed.
   - Every export is logged.
   - **Later:** a cited-page appendix and re-verifying a pack against the current documents.

**Exit:** the pack's hash validates, the excerpts match the stored chunks, and OCR'd or
low-confidence sources are visibly marked.

## Phase 4. Gap comparison & OCR

**ECC:** `/orch-add-feature`.
**Review:** Compliance Auditor agent.

**Policy-vs-regulation comparison**, run as a background job per workspace:

1. Extract requirements locally with a numbered-clause parser (0 LLM calls).
2. Retrieve the top 3 passages from our policy for each requirement.
3. Requirements whose best score is below the medium threshold become "No matching passage
   found", with no LLM call.
4. Classify the rest in one batched call per 15–20 requirements, asking for JSON.
   - A 40-clause regulation costs about 2–3 requests, and the estimate is shown before running.
   - Progress is checkpointed so a quota stop can resume.
   - Each quote is validated by exact substring; one that doesn't match becomes "Needs review".
5. Statuses are *Addressed / Partially addressed / No matching passage / Needs review*.
   There's **no compliance score**, and a reviewer can sign off each row.
6. Results export as an evidence pack.

**OCR:**

- Uses PyMuPDF with Tesseract: `brew install tesseract` locally, and `tesseract-ocr` in Docker.
- Opt-in per workspace.
- Only pages with no text layer are OCR'd, with a page cap per upload.
- OCR'd chunks are flagged: a chip in the UI, confidence capped at medium, and a mark in packs.

**Exit:** the comparison runs on GDPR sample vs company policy within ≤ 3 chat calls; a
scanned sample is indexed with the OCR flag shown end to end.

## Phase 5. Hardening & release

- `ecc:security-review` and `/fastapi-review` on the whole v3 diff.
- An accessibility re-audit of the new pages (Accessibility Auditor agent).
- `ecc:e2e-testing`: Playwright for login → upload → streamed cited answer → export.
- Docker and compose updated (Tesseract, the SQLite volume, the proxy).
- README, an `.env.example` refresh, and migration notes.

---

## Deliberately not in v3

Email invites, SSO, billing, Postgres/pgvector, public hosting, questionnaire bulk import,
LLM re-ranking, and any "you are compliant" verdict.

## Top risks

1. SSE and uploads through the Next proxy. Phase 0 settles this first.
2. Data leaking between workspaces through a leftover global store. Mitigated by the authorisation matrix and 404 tests.
3. The library migration can't be undone. Mitigated by an automatic backup and a dry-run CLI.
4. Opening a store with a changed `embedding_id` re-embeds everything and burns quota. Re-indexes run only by explicit admin action, with an estimate shown first.
5. Section-regex false positives. Mitigated by monotonic guards, the fallback splitter and golden-set floors.

## Your actions needed along the way

- Phase 4 OCR: run `brew install tesseract` once (about 30–60 MB).
- Live eval runs use some of the daily Gemini quota. A second free key or an OpenAI key makes
  evals painless, but neither is required.
