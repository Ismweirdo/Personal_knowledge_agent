FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt ./
ARG PYPI_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch \
    && python -m pip install --no-cache-dir --index-url ${PYPI_INDEX_URL} -r requirements.txt
COPY app.py ./

ENV MODEL_NAME=BAAI/bge-m3
ENV MODEL_CACHE_DIR=/models
ENV EMBEDDING_BATCH_SIZE=4
EXPOSE 8001
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8001"]
