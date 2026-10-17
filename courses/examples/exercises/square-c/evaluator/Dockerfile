FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY evaluate.py /app/evaluate.py

ENTRYPOINT ["python3", "/app/evaluate.py"]
