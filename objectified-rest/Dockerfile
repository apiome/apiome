# Dockerfile for Objectified REST (FastAPI)
# Supports: linux/amd64, linux/arm64

FROM --platform=$BUILDPLATFORM python:3.12-slim

WORKDIR /app

# Runtime dependency for psycopg2-binary
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies (requirements.txt + extras from pyproject.toml)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    bcrypt==4.2.0 \
    email-validator==2.2.0

# Copy application
COPY src/ /app/src/

# Non-root user
RUN useradd --create-home --uid 1000 appuser && chown -R appuser:appuser /app
USER appuser

ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
