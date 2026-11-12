# Lumina evals

Black-box checks that answers are grounded and cited, that out-of-scope and invented
questions are declined, and that injection attempts are blocked. They call a running
API, so they use your OpenAI key.

```bash
python -m backend.scripts.ingest_folder samples   # once, from the repo root
uvicorn backend.main:app --port 8000               # in another terminal
npx promptfoo@latest eval -c promptfoo-tests/promptfooconfig.yaml
npx promptfoo@latest view                          # browse results
```
