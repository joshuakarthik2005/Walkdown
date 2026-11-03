# Walkdown public demo API (Render free web service: 512 MB RAM, 0.1 CPU, ephemeral disk).
# Sample frames, caches and finished examples are not in this repo or image: the container downloads them at
# start from a private Hugging Face dataset with HF_TOKEN (backend/api/bundle.py).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # glibc keeps one malloc arena per thread by default; two keeps the worker threads from inflating RSS.
    MALLOC_ARENA_MAX=2 \
    DEMO_MODE=true \
    WALKDOWN_DATA_DIR=/data \
    WALKDOWN_SOLVER_WORKERS=2

WORKDIR /app
COPY requirements-demo.txt .
RUN pip install --no-cache-dir -r requirements-demo.txt
COPY backend ./backend

RUN useradd --create-home walkdown && mkdir -p /data && chown walkdown /data
USER walkdown

EXPOSE 10000
# One worker: runs live in process memory.
CMD ["sh", "-c", "python -m backend.api.bundle fetch; exec uvicorn backend.api.app:app --host 0.0.0.0 --port ${PORT:-10000} --workers 1 --proxy-headers --forwarded-allow-ips='*'"]
