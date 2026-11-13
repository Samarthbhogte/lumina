"""Offline demo server: the real API with fake embeddings and a scripted model.

Use it to work on the UI without an OpenAI key or cost:

    uvicorn backend.devserver:app --port 8000

Retrieval is not semantic (embeddings are hash-based) and every answer is the same
template citing the top passages, so use it for UI and API plumbing only.
"""

import asyncio
import itertools
import os
from collections.abc import Iterator

from langchain_core.embeddings import DeterministicFakeEmbedding
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from backend.config import ROOT_DIR, get_settings
from backend.main import create_app

DEMO_ANSWER = (
    "**Demo mode:** this answer is scripted, not generated.\n\n"
    "The documents set out the relevant obligation in plain terms [1], and a related clause "
    "adds detail on how it is applied [2].\n\n"
    "- Records should be kept for the stated period and reviewed regularly [1].\n"
    "- Exceptions must be documented and approved [2][3]."
)


class _SlowFake(GenericFakeChatModel):
    """Optional per-token delay (LUMINA_DEMO_TOKEN_DELAY seconds) to make streaming visible."""

    async def _astream(self, *args, **kwargs):
        delay = float(os.getenv("LUMINA_DEMO_TOKEN_DELAY", "0"))
        async for chunk in super()._astream(*args, **kwargs):
            if delay:
                await asyncio.sleep(delay)
            yield chunk


def _answers() -> Iterator[AIMessage]:
    # Follow-up questions make an extra "condense" call; any text works for that.
    return (AIMessage(DEMO_ANSWER) for _ in itertools.count())


settings = get_settings().model_copy(update={"data_dir": ROOT_DIR / "data-demo", "chat_model": "demo (offline)"})
app = create_app(
    settings,
    embeddings=DeterministicFakeEmbedding(size=256),
    llm=_SlowFake(messages=_answers()),
)
