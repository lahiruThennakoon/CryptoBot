FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

COPY pyproject.toml ./
COPY src ./src
RUN pip install .

COPY alembic.ini ./
COPY alembic ./alembic

# Non-root user
RUN useradd -m bot && chown -R bot /app
USER bot

CMD ["uvicorn", "cryptobot.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
