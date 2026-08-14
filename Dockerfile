FROM python:3.12-slim

ARG HUNT_BOARD_RELEASE=development
LABEL org.opencontainers.image.title="Hunt Board" \
    org.opencontainers.image.version="${HUNT_BOARD_RELEASE}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN groupadd --system huntboard && useradd --system --gid huntboard --home-dir /app huntboard \
    && pip install --no-cache-dir uv
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

COPY alembic ./alembic
COPY alembic.ini ./alembic.ini
COPY data ./data

RUN chown -R huntboard:huntboard /app
USER huntboard

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=3)"
CMD ["sh", "-c", "alembic upgrade head && hunt-board seed && exec uvicorn hunt_board.main:app --host 0.0.0.0 --port 8000"]
