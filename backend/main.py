"""Lumina API. Run from the repository root: uvicorn backend.main:app --reload"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from langchain_core.embeddings import Embeddings
from langchain_core.runnables import Runnable

from backend.account_api import router as account_router
from backend.api import router
from backend.compare_api import router as compare_router
from backend.config import Settings, get_settings
from backend.db import make_engine, make_sessionmaker
from backend.providers import PROVIDER_ERRORS, build_models, classify, rate_limit_message
from backend.rag import RagService
from backend.registry import StoreRegistry

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("lumina")


class _MissingKeyEmbeddings(Embeddings):
    """Stand-in that lets the app start (and list documents) before a key is configured."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("No AI provider API key is set.")

    def embed_query(self, text: str) -> list[float]:
        raise RuntimeError("No AI provider API key is set.")


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
    llm: Runnable | None = None,
) -> FastAPI:
    """Build the app. Tests pass fake embeddings and a fake chat model."""
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        emb, chat = embeddings, llm
        if emb is None and chat is None:
            emb, chat = build_models(settings)
        app.state.settings = settings
        app.state.ai_ready = emb is not None and chat is not None
        app.state.engine = make_engine(settings.db_path)
        app.state.sessionmaker = make_sessionmaker(app.state.engine)
        app.state.registry = StoreRegistry(settings, emb or _MissingKeyEmbeddings(), settings.embedding_id)
        app.state.rag = RagService(chat, settings) if chat else None
        if not app.state.ai_ready:
            logger.warning("%s is not set: uploads and questions are disabled.", settings.api_key_name)
        else:
            logger.info(
                "Provider %s: chat=%s embeddings=%s", settings.provider, settings.chat_model, settings.embedding_model
            )
        yield
        app.state.engine.dispose()

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

    async def _provider_errors(_: Request, exc: Exception):
        kind = classify(exc)
        label = settings.provider_label
        if kind == "auth":
            logger.error("%s rejected the API key: %s", label, exc)
            return JSONResponse(status_code=502, content={"detail": f"{label} rejected the API key."})
        if kind == "rate":
            logger.warning("%s", rate_limit_message(exc, label))
            return JSONResponse(status_code=503, content={"detail": rate_limit_message(exc, label)})
        logger.exception("Unhandled error" if kind is None else f"{label} request failed")
        detail = "Internal server error." if kind is None else f"The {label} request failed."
        return JSONResponse(status_code=500 if kind is None else 502, content={"detail": detail})

    # Registered per provider base class (not bare Exception, which Starlette re-raises).
    for error_type in PROVIDER_ERRORS:
        app.add_exception_handler(error_type, _provider_errors)

    app.include_router(account_router)
    app.include_router(router)
    app.include_router(compare_router)
    # Outermost, so the size cap and headers also apply to CORS and error responses.
    app.add_middleware(_Guard, max_body=settings.max_request_bytes)

    @app.get("/", include_in_schema=False)
    def root():
        return {"name": "Lumina API", "docs": "/docs", "health": "/api/health"}

    return app


app = create_app()
