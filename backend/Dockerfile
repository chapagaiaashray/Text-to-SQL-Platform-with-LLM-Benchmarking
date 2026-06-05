FROM python:3.12-slim

# psycopg[binary] ships its own libpq, so no system libpq-dev needed.
# build-essential kept minimal; remove if no source builds are required.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install deps first so Docker layer-caches them across code changes.
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy application code.
COPY backend ./backend

# Non-root user for safety.
RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Default command (overridden by docker-compose for --reload in dev).
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
