"""Lumina API. Run from the repository root: uvicorn backend.main:app --reload"""

import logging
from contextlib import asynccontextmanager

import openai
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel

from backend.api import router
from backend.config import Settings, get_settings
from backend.rag import RagService
from backend.store import DocumentStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("lumina")


class _MissingKeyEmbeddings(Embeddings):
    """Stand-in that lets the app start (and list documents) before a key is configured."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("OPENAI_API_KEY is not set.")

    def embed_query(self, text: str) -> list[float]:
        raise RuntimeError("OPENAI_API_KEY is not set.")


class _Guard:
    """Pure ASGI middleware: security headers on every response, and a hard cap on request
    bodies so an oversized multipart upload is refused before it is spooled to disk."""

    HEADERS = [
        (b"x-content-type-options", b"nosniff"),
        (b"referrer-policy", b"no-referrer"),
        (b"x-frame-options", b"DENY"),
    ]

    def __init__(self, app, max_body: int):
        self.app = app
        self.max_body = max_body

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        length = dict(scope["headers"]).get(b"content-length")
        if length is not None and int(length) > self.max_body:
            response = JSONResponse({"detail": "Upload is too large."}, status_code=413)
            return await response(scope, receive, send)

        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_body:
                    raise _TooLarge
            return message

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                message["headers"] = list(message.get("headers", [])) + self.HEADERS
            await send(message)

        try:
            await self.app(scope, limited_receive, send_with_headers)
        except _TooLarge:
            response = JSONResponse({"detail": "Upload is too large."}, status_code=413)
            await response(scope, receive, send)


class _TooLarge(Exception):
    pass


def create_app(
    settings: Settings | None = None,
    embeddings: Embeddings | None = None,
    llm: BaseChatModel | None = None,
) -> FastAPI:
    """Build the app. Tests pass fake embeddings and a fake chat model."""
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        emb, chat = embeddings, llm
        if emb is None and settings.openai_api_key:
            from langchain_openai import OpenAIEmbeddings

            emb = OpenAIEmbeddings(model=settings.embedding_model, api_key=settings.openai_api_key)
        if chat is None and settings.openai_api_key:
            from langchain_openai import ChatOpenAI

            chat = ChatOpenAI(
                model=settings.chat_model,
                temperature=settings.temperature,
                api_key=settings.openai_api_key,
                max_retries=2,
                timeout=60,
            )
        app.state.settings = settings
        app.state.ai_ready = emb is not None and chat is not None
        app.state.store = DocumentStore(
            settings.data_dir,
            emb or _MissingKeyEmbeddings(),
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
            max_chunks=settings.max_chunks_per_document,
        )
        app.state.rag = RagService(app.state.store, chat, settings) if chat else None
        if not app.state.ai_ready:
            logger.warning("OPENAI_API_KEY is not set: uploads and questions are disabled.")
        yield

    app = FastAPI(
        title="Lumina API",
        description="Upload policy PDFs and ask compliance questions with page-level citations.",
        version="2.0.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.enable_docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.enable_docs else None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type"],
    )

    @app.exception_handler(openai.AuthenticationError)
    async def _openai_auth(_: Request, exc: openai.AuthenticationError):
        logger.error("OpenAI rejected the API key: %s", exc)
        return JSONResponse(status_code=502, content={"detail": "OpenAI rejected the API key."})

    @app.exception_handler(openai.RateLimitError)
    async def _openai_rate(_: Request, exc: openai.RateLimitError):
        logger.error("OpenAI rate limit or quota: %s", exc)
        return JSONResponse(
            status_code=503,
            content={"detail": "OpenAI rate limit or quota reached. Try again shortly."},
        )

    @app.exception_handler(openai.APIError)
    async def _openai_other(_: Request, exc: openai.APIError):
        logger.error("OpenAI request failed: %s", exc)
        return JSONResponse(status_code=502, content={"detail": "The AI provider request failed."})

    app.include_router(router)
    # Outermost, so the size cap and headers also apply to CORS and error responses.
    app.add_middleware(_Guard, max_body=settings.max_request_bytes)

    @app.get("/", include_in_schema=False)
    def root():
        return {"name": "Lumina API", "docs": "/docs", "health": "/api/health"}

    return app


app = create_app()
