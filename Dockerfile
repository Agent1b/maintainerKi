FROM python:3.12-slim

ARG INSTALL_SEMANTIC_DUPLICATES=false

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
COPY requirements.semantic-duplicates.txt ./
RUN pip install --upgrade pip \
    && pip install -r requirements.txt \
    && if [ "$INSTALL_SEMANTIC_DUPLICATES" = "true" ]; then pip install -r requirements.semantic-duplicates.txt; fi

COPY server ./server
COPY worker ./worker
COPY scripts ./scripts
COPY db_migrations ./db_migrations
COPY alembic.ini ./
COPY docs ./docs
COPY .env.example ./
COPY README.md ./

RUN useradd --create-home --shell /usr/sbin/nologin maintainerki \
    && chown -R maintainerki:maintainerki /app

USER maintainerki

EXPOSE 8000

CMD ["uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8000"]
