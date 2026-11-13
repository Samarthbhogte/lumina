# Lumina v3: product brief

*Product-lens diagnostic and feature prioritisation, 2026-11-12.*

## 1. Who is it for?

**Primary:** a compliance, privacy or security analyst at a 20–500-person company. They own a
small library of policies (privacy policy, data retention, incident response, vendor
management) plus the regulations those policies answer to (GDPR, HIPAA and so on).

**Secondary:** the auditor or customer reviewer who receives their answers, and a
student or portfolio reviewer evaluating the build.

## 2. What's the pain?

Several times a month, often weekly, someone asks *"Does our policy cover X, and where?"*
The askers are an auditor, a customer's security questionnaire, a new regulation, or a
colleague. Today the analyst searches the PDFs with Ctrl+F, copies clauses into a
spreadsheet, and pastes evidence by hand. Each question takes 10–30 minutes, and
**proving** the answer matters as much as the answer itself.

Lumina v2 already answers with file and page citations. Three things stop it from replacing
the spreadsheet:

- Citations stop at the page, when auditors cite clauses (§7.2).
- There's no way to hand the evidence to anyone else.
- It's single-user, so no team can share one library or keep a history.

## 3. Why now?

LLMs and embeddings are now cheap enough to run on a free tier. Trust is what's still
missing, and it comes from verifiable citations, not fluent answers. That makes
evidence-first answers a defensible position against "just ask ChatGPT".

## 4. The 10-star version

Drop in a 200-question security questionnaire. Each item is answered from your policy
library with clause-level evidence and a gap flag where coverage is weak, then exported as a
versioned evidence pack your auditor accepts without follow-up questions.

## 5. MVP thesis for v3

> **A reviewer can verify any Lumina answer in under 30 seconds, and hand an auditor an
> evidence pack without editing it.**

Everything in v3 is judged against that sentence.

## 6. Anti-goals for v3

- No legal advice or "you are compliant" verdicts. Lumina shows evidence and its strength.
- No open-ended chat or world-knowledge answers. They stay declined, as today.
- No enterprise SSO, billing or hosted multi-tenant SaaS. Self-hosted, small teams.
- No fine-tuning and no paid reranking APIs. The free-tier quota is a design constraint.

## 7. How we'll know it's working

| Metric | v2 baseline | v3 target |
| --- | --- | --- |
| Golden-set retrieval recall@6 (expected clause in the retrieved sources) | not measured | ≥ 0.90 |
| Answers whose citations name a section, not just a page | 0% | ≥ 80% on the samples |
| LLM calls per question (free-tier budget) | 1, or 2 for follow-ups | ≤ 1.2 on average |
| Time to verify an answer (click a citation, see the clause) | about 15 s | under 30 s, including the export |
| Evidence pack opens and validates with no edits | n/a | yes, with an integrity hash |

## 8. Feature prioritisation (ICE)

Scores are impact × confidence ÷ effort, each rated 1–5.

| Feature | I | C | E | ICE | Note |
| --- | --- | --- | --- | --- | --- |
| Golden-set retrieval evals (offline, pytest) | 4 | 5 | 1 | **20.0** | Foundation: measures every later change for free |
| Clause-aware chunking and section citations | 5 | 5 | 2 | **12.5** | Directly serves the MVP thesis |
| Audit-ready evidence export (PDF + JSON) | 5 | 4 | 2 | **10.0** | The handoff that replaces the spreadsheet |
| Hybrid BM25 + vector search with local re-ranking | 4 | 4 | 2 | **8.0** | Exact-term queries ("CPNI", "§7.2") currently rely on embeddings alone |
| OCR for scanned PDFs (local) | 3 | 4 | 2 | **6.0** | Common in real policy libraries |
| Accounts, workspaces, server-side history, per-user quota | 4 | 4 | 4 | **4.0** | Required for teams and real use; the biggest and riskiest piece |
| Policy-vs-regulation gap comparison | 5 | 3 | 4 | **3.75** | High value but quota-heavy; needs good retrieval first |

## 9. Sequencing (dependencies first)

1. **Retrieval foundation:** golden-set evals, then clause-aware chunks, hybrid search and
   re-ranking. Everything after builds on better citations.
2. **Evidence export:** single answers and whole sessions.
3. **Accounts and workspaces:** sign-in, personal and shared workspaces, conversations stored
   on the server, per-user quota. Existing data migrates into the first account.
4. **Gap comparison and OCR:** comparison reuses the improved retrieval, and runs as a
   budgeted batch job inside a workspace.

## 10. Cut or defer

- **Email invites** (they need a mail service). v3 uses copyable invite links instead.
- **Answer-history analytics dashboards** and **questionnaire bulk import**. Both are good
  v3.1 candidates, once the gap comparison exists.
- **Postgres/pgvector and public deployment.** Out of scope by choice. Keep SQLite and FAISS,
  behind interfaces.

## 11. Recommendation

**Go.** Build in the order above. The main risk is accounts and workspaces (auth bugs, data
leaking between workspaces). Isolate it behind workspace-scoped stores and test it hardest.
