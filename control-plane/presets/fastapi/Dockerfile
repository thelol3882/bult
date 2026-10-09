# bult preset: FastAPI (Python).
# Your repository needs: requirements.txt; the ASGI app `app` in main.py;
# the app must listen on $PORT (the platform sets it). Demo: examples/fastapi-hello.

FROM python:3.11-slim AS builder

WORKDIR /build

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc build-essential && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir --user -r requirements.txt


FROM python:3.11-slim AS runner

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    PATH="/home/appuser/.local/bin:$PATH"

RUN groupadd --gid 10001 appuser && \
    useradd --uid 10001 --gid appuser --shell /sbin/nologin --create-home appuser

COPY --from=builder --chown=appuser:appuser /root/.local /home/appuser/.local

COPY --chown=appuser:appuser . .

USER appuser

EXPOSE ${PORT}

CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
