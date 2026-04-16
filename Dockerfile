FROM python:3.11-slim

WORKDIR /app

# Layer caching: install dependencies first
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Create data directory for SQLite (mount a persistent volume here on Northflank)
RUN mkdir -p /app/data

EXPOSE 3000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "3000"]
