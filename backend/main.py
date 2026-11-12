# backend/main.py

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# ✅ Load environment variables from .env file (before any route imports)
load_dotenv()

# ✅ Absolute imports for clean structure
from backend.routes.upload_route import router as upload_router
from backend.routes.query_route import router as query_router
from backend.routes.ask_route import router as ask_router

# ✅ Initialize FastAPI app
app = FastAPI(
    title="Lumina AI - Compliance Assistant",
    description="Upload policy PDFs, ask compliance questions, get AI-powered responses via LangChain + OpenAI.",
    version="1.0.0"
)

# ✅ Enable CORS (configure allowed origins securely for production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # 🔒 TODO: Use env var or strict origin(s) in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ✅ Register API routes
app.include_router(upload_router, prefix="/api", tags=["Upload"])
app.include_router(query_router, prefix="/api", tags=["Query"])
app.include_router(ask_router, prefix="/api")

# ✅ Health check endpoint
@app.get("/health")
def health_check():
    return {"status": "ok", "message": "🚀 Lumina backend is live!"}

# ✅ Root welcome route
@app.get("/")
def root():
    return {
        "message": "👋 Welcome to Lumina Backend (LangChain Mode)",
        "endpoints": {
            "health": "/health",
            "upload": "/api/upload",
            "query": "/api/ask"
        },
        "docs": "/docs"
    }
