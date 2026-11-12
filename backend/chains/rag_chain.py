# backend/chains/rag_chain.py
from langchain_openai import ChatOpenAI
from langchain.prompts import PromptTemplate
from langchain.chains import LLMChain

# ✅ Refined Prompt Template (more flexible, still safe)
QA_TEMPLATE = """
You are Lumina, a reliable AI legal compliance assistant. Your role is to provide helpful and accurate answers using the context below.

Guidelines:
- Maintain a formal tone and professional clarity.
- Use only the information in the context, but you can paraphrase or summarize.
- Do not invent facts that are not supported by the context.
- If the answer is unclear or missing, respond:
  "I don’t know based on the document."
- If the question is unrelated to compliance, respond:
  "This question appears to be outside the scope of the compliance document."

Context:
{context}

Question:
{question}

Formal Response:
"""

def build_qa_chain():
    prompt = PromptTemplate(
        input_variables=["context", "question"],
        template=QA_TEMPLATE.strip(),
    )

    llm = ChatOpenAI(
        model="gpt-4",
        temperature=0.2,  # 🔥 Reduced temperature for stability
    )

    return LLMChain(
        llm=llm,
        prompt=prompt,
        verbose=False,
    )
