# RiskLens: FastAPI + XGBoost web app. Runs on any Docker host.
FROM python:3.12-slim

# XGBoost needs the OpenMP runtime on Linux.
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY risklens ./risklens
COPY app ./app

COPY data/processed ./data/processed
COPY models ./models

ENV PYTHONUNBUFFERED=1 PORT=8000
EXPOSE 8000
# Hosts inject $PORT; default to 8000 locally.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
