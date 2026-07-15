FROM python:3.12-slim

WORKDIR /app
RUN set -eux; \
    for attempt in 1 2 3; do \
      apt-get update \
      && apt-get install -y --no-install-recommends -o Acquire::Retries=5 git \
      && rm -rf /var/lib/apt/lists/* \
      && break; \
      rm -rf /var/lib/apt/lists/*; \
      if [ "$attempt" = "3" ]; then exit 1; fi; \
    done
COPY pyproject.toml ./
COPY app ./app
COPY alembic.ini ./
COPY alembic ./alembic
RUN pip install --no-cache-dir .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
