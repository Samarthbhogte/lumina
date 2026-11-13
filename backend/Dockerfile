# Build from the repository root: docker build -f backend/Dockerfile .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 LUMINA_DATA_DIR=/app/data
WORKDIR /app

# Tesseract lets Lumina read scanned PDFs (OCR runs locally).
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend backend
RUN useradd --create-home lumina && mkdir -p /app/data && chown lumina:lumina /app/data && chmod 700 /app/data
USER lumina

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"
# Trust X-Forwarded-For only from the Next.js proxy (set FORWARDED_ALLOW_IPS to its address or
# network), so login throttling and audit logs see real client IPs rather than the proxy's.
ENV FORWARDED_ALLOW_IPS=127.0.0.1
CMD ["sh", "-c", "exec uvicorn backend.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips \"$FORWARDED_ALLOW_IPS\""]
