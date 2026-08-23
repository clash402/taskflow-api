FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && \
    apt-get upgrade -y && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

FROM base AS ci

COPY pyproject.toml /app/pyproject.toml
COPY main.py /app/main.py
COPY src /app/src
COPY tests /app/tests

RUN python -m pip install --upgrade pip setuptools && \
    pip install ".[dev]"

FROM base AS runtime

COPY pyproject.toml /app/pyproject.toml
COPY main.py /app/main.py
COPY src /app/src

RUN python -m pip install --upgrade pip setuptools && \
    pip install . && \
    python -m pip uninstall -y pip

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
