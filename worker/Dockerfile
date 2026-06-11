# Build from the REPO ROOT so the worker reuses the main app's modules
# (config.py, db/, evaluation/, pipeline/) instead of carrying forked copies:
#   docker build -f worker/Dockerfile .
FROM python:3.12-slim
WORKDIR /app

COPY worker/requirements.txt ./worker-requirements.txt
RUN pip install --no-cache-dir -r worker-requirements.txt

COPY config.py ./
COPY db/ ./db/
COPY evaluation/ ./evaluation/
COPY pipeline/ ./pipeline/
COPY worker/ ./worker/

RUN mkdir -p /app/data

EXPOSE 3000

CMD sh -c "uvicorn worker.main:app --host 0.0.0.0 --port ${PORT:-3000}"
