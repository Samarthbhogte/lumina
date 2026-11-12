# Build from the repository root: docker build -f backend/Dockerfile .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 LUMINA_DATA_DIR=/app/data
WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend backend
RUN useradd --create-home lumina && mkdir -p /app/data && chown lumina:lumina /app/data && chmod 700 /app/data
USER lumina

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
