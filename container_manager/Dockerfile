FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY shared /app/shared
COPY container_manager/src /app/container_manager/src

ENV PYTHONPATH=/app

CMD ["uvicorn", "container_manager.src.app:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "1"]
