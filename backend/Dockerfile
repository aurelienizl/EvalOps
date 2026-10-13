FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY shared /app/shared
COPY backend/src /app/backend/src

ENV PYTHONPATH=/app

CMD ["uvicorn", "backend.src.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
