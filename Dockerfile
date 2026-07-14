FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN pip install --no-cache-dir uv
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

COPY alembic ./alembic
COPY alembic.ini ./alembic.ini
COPY data ./data

EXPOSE 8000
CMD ["uvicorn", "hunt_board.main:app", "--host", "0.0.0.0", "--port", "8000"]
