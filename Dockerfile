# Stage 1: Build frontend
FROM node:20-alpine AS frontend-builder
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npx vite build

# Stage 2: Python app
FROM python:3.11-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Copy built frontend from stage 1
COPY --from=frontend-builder /frontend/dist ./frontend/dist

# Create data directory for SQLite (mount a persistent volume here on Northflank)
RUN mkdir -p /app/data

EXPOSE 3000

CMD sh -c "uvicorn main:app --host 0.0.0.0 --port ${PORT:-3000}"
