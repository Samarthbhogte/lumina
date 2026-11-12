# backend/utils/embed_store.py

from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import OpenAIEmbeddings
from langchain.docstore.document import Document
from langchain.text_splitter import RecursiveCharacterTextSplitter
from backend.utils.pdf_parser import extract_text_from_pdf
import os
import json
import glob

class PersistentEmbedStore:
    def __init__(self, persist_path="data/vector_store"):
        self.persist_path = persist_path
        self.embedding_model = OpenAIEmbeddings(model="text-embedding-ada-002")

        if os.path.exists(persist_path):
            print(f"📂 Loading existing FAISS store from: {persist_path}")
            try:
                self.vectorstore = FAISS.load_local(
                    persist_path,
                    self.embedding_model,
                    allow_dangerous_deserialization=True
                )
                print("✅ Vector store loaded successfully.")
            except Exception as e:
                print(f"❌ Failed to load vector store: {e}")
                self.vectorstore = None
        else:
            print("🆕 No existing FAISS store found. Initializing new one.")
            self.vectorstore = None  # Created upon first document

    def add_document(self, text: str, source: str):
        print(f"📥 Adding document from: {source}")
        if not text.strip():
            print("⚠️ Empty or invalid text received. Skipping.")
            return

        print(f"🧪 Preview of text being embedded:\n{text[:500]}\n---")

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=800,
            chunk_overlap=50
        )

        docs = splitter.create_documents([text], metadatas=[{"source": source}])

        if self.vectorstore:
            self.vectorstore.add_documents(docs)
            print(f"✅ {len(docs)} chunks added to existing vector store.")
        else:
            try:
                print("🔧 Creating new FAISS vector store...")
                self.vectorstore = FAISS.from_documents(docs, self.embedding_model)
                print("✅ Vector store created with", len(docs), "chunks.")
            except Exception as e:
                print(f"❌ Failed to create FAISS store: {e}")
                raise

        self.vectorstore.save_local(self.persist_path)
        print("💾 Vector store saved to disk.")

    def query(self, question: str, k: int = 10):
        if not self.vectorstore:
            print("❌ No vector store found. Cannot query.")
            return []

        print(f"\n🔍 Querying vector store with: {question}")
        results = self.vectorstore.similarity_search(question, k=k)
        print(f"🔗 Retrieved {len(results)} result(s) from FAISS.")

        for i, res in enumerate(results, 1):
            print(f"\n--- Result #{i} ---")
            print(f"Text Snippet: {res.page_content[:200]}...")
            print(f"Metadata: {json.dumps(res.metadata)}")

        return [
            {
                "text": res.page_content,
                "source": res.metadata.get("source", "unknown")
            }
            for res in results
        ]

    def index_pdfs_from_folder(self, folder_path: str = "data/pdfs"):
        """
        Batch index all PDFs in the folder.
        """
        pdf_paths = glob.glob(os.path.join(folder_path, "*.pdf"))
        if not pdf_paths:
            print("📁 No PDFs found in folder:", folder_path)
            return

        for path in pdf_paths:
            try:
                print(f"\n📄 Processing: {os.path.basename(path)}")
                text = extract_text_from_pdf(path)
                self.add_document(text, source=os.path.basename(path))
            except Exception as e:
                print(f"❌ Failed to process {path}: {e}")
