from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from backend.utils.embed_store import PersistentEmbedStore
from backend.chains.rag_chain import build_qa_chain
from backend.utils.performance_logger import log_performance
import os
import logging

router = APIRouter()
embed_store = PersistentEmbedStore()

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

class Question(BaseModel):
    question: str

# Detect basic prompt injection
def detect_prompt_injection(text: str) -> bool:
    dangerous_phrases = [
        "ignore previous", "disregard", "act as", "jailbreak", 
        "simulate", "you are no longer", "override", "system message"
    ]
    return any(phrase in text.lower() for phrase in dangerous_phrases)

@router.post("/ask")
@log_performance
async def ask_question(data: Question):
    question = data.question.strip()
    logger.info(f"🔍 Incoming question: {question}")

    if len(question) < 6:
        return {
            "answer": "❗ Please enter a more specific compliance-related question.",
            "source_documents": []
        }

    if detect_prompt_injection(question):
        logger.warning("🚨 Prompt injection attempt detected.")
        return {
            "answer": "⚠️ Your question contains prohibited instructions.",
            "source_documents": []
        }

    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(status_code=500, detail="Missing OpenAI API Key.")

    try:
        results = embed_store.query(question)
        logger.info(f"📄 Retrieved {len(results)} documents from vector store.")

        if not results:
            return {
                "answer": "❗ No relevant content found in uploaded documents.",
                "source_documents": []
            }

        context = "\n\n".join([res["text"] for res in results])
        sources = list({res["source"] for res in results})

        if not context:
            logger.warning("⚠️ Context is empty after retrieval.")
            return {
                "answer": "⚠️ Failed to extract usable content. Please re-upload documents.",
                "source_documents": []
            }

        # Truncate to fit token limit
        if len(context) > 6000:
            logger.info("✂️ Truncating context to 6000 characters for token limit.")
            context = context[:6000]

        chain = build_qa_chain()
        response = chain.invoke({"question": question, "context": context})
        logger.info(f"✅ LLM Response: {response}")

        return {
            "answer": response.get("text", "⚠️ No answer found."),
            "source_documents": [{"source": src} for src in sources]
        }

    except Exception as e:
        logger.exception("❌ /ask endpoint failed")
        raise HTTPException(status_code=500, detail=str(e))
