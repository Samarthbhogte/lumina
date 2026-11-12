# backend/routes/upload_route.py

from fastapi import APIRouter, File, UploadFile, HTTPException
from typing import List
from backend.utils.embed_store import PersistentEmbedStore
from backend.utils.pdf_parser import extract_text_from_pdf
import logging

router = APIRouter()
embed_store = PersistentEmbedStore()

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

@router.post("/upload")
async def upload_files(files: List[UploadFile] = File(...)):
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded.")

    results = []
    for file in files:
        try:
            content = await file.read()
            logger.info(f"📥 Received upload: {file.filename} | Size: {len(content)} bytes")

            text = extract_text_from_pdf(content)
            if not text.strip():
                logger.warning(f"⚠️ No readable text in: {file.filename}")
                results.append({
                    "filename": file.filename,
                    "status": "❌ Skipped: No extractable text."
                })
                continue

            embed_store.add_document(text, source=file.filename)
            logger.info(f"✅ Embedded: {file.filename}")

            results.append({
                "filename": file.filename,
                "status": "✅ Embedded successfully.",
                "preview": text[:300] + "..." if len(text) > 300 else text
            })

        except Exception as e:
            logger.error(f"❌ Failed to process {file.filename}: {e}")
            results.append({
                "filename": file.filename,
                "status": f"❌ Error: {str(e)}"
            })

    return {
        "summary": f"Processed {len(results)} file(s)",
        "results": results
    }
