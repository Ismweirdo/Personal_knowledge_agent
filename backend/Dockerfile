FROM python:3.12-slim

WORKDIR /app
RUN set -eux; \
    sed -i 's|http://deb.debian.org/debian|https://mirrors.tencent.com/debian|g' /etc/apt/sources.list.d/debian.sources; \
    sed -i 's|http://deb.debian.org/debian-security|https://mirrors.tencent.com/debian-security|g' /etc/apt/sources.list.d/debian.sources; \
    for attempt in 1 2 3; do \
      apt-get update \
      && apt-get install -y --no-install-recommends -o Acquire::Retries=5 git \
      && rm -rf /var/lib/apt/lists/* \
      && break; \
      rm -rf /var/lib/apt/lists/*; \
      if [ "$attempt" = "3" ]; then exit 1; fi; \
    done
ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ENV PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn
ENV PIP_DEFAULT_TIMEOUT=120
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
COPY pyproject.toml ./
COPY app ./app
COPY alembic.ini ./
COPY alembic ./alembic
RUN python -m pip install --no-cache-dir --upgrade pip setuptools wheel hatchling \
    && python -m pip install --no-cache-dir --no-build-isolation .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
