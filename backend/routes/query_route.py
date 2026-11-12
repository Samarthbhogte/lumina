from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from backend.utils.embed_store import PersistentEmbedStore
from backend.chains.rag_chain import build_qa_chain
import os
import logging

# Initialize FastAPI router and components
router = APIRouter()
embed_store = PersistentEmbedStore()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Input schema
class Question(BaseModel):
    question: str

# Ask endpoint
@router.post("/ask")
async def ask_question(data: Question):
    question = data.question.strip()
    logger.info(f"📥 Received question: {question}")

    # Basic validation
    if not question or len(question) < 5:
        return {
            "answer": "Please enter a more specific question.",
            "sources": [],
            "source_documents": []
        }

    # Check for OpenAI API key
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(status_code=500, detail="Missing OpenAI API key.")

    try:
        # Query the vector store for relevant chunks
        results = embed_store.query(question)
        if not results:
            return {
                "answer": "No relevant content found in the uploaded documents.",
                "sources": [],
                "source_documents": []
            }

        # Build the context string from top results
        context = "\n\n".join([res["text"] for res in results])
        if len(context) > 6000:
            context = context[:6000] + "..."

        # Build and invoke the RAG chain
        chain = build_qa_chain()
        llm_response = chain.invoke({
            "question": question,
            "context": context
        })

        logger.info(f"✅ LLM response: {llm_response}")

        # Extract clean answer
        answer = llm_response.get("answer") or llm_response.get("text") or "No answer found."

        # Extract document sources
        sources = list(set(res["source"] for res in results))

        return {
            "answer": answer,
            "sources": sources,
            "source_documents": sources  # You can replace this with actual docs if needed
        }

    except Exception as e:
        logger.exception("❌ Internal error in /ask:")
        raise HTTPException(status_code=500, detail="Something went wrong while processing your question.")
