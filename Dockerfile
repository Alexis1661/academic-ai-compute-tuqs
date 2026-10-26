FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install runtime dependencies first (layer cached until pyproject.toml changes)
COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir .

COPY . .
RUN mkdir -p /app/data

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8000/api/v1/health || exit 1

# Alembic migrations run in the FastAPI lifespan (AUTO_MIGRATE=true)
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
