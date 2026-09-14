"""OpenAI-compatible local BGE-M3 embedding service."""

import os
from contextlib import asynccontextmanager
from time import time
import numpy as np
from fastapi import FastAPI, HTTPException
from FlagEmbedding import BGEM3FlagModel
from pydantic import BaseModel, Field

MODEL_NAME = os.getenv("MODEL_NAME", "BAAI/bge-m3")
MODEL_CACHE_DIR = os.getenv("MODEL_CACHE_DIR", "/models")
BATCH_SIZE = int(os.getenv("EMBEDDING_BATCH_SIZE", "4"))


class EmbeddingRequest(BaseModel):
    input: str | list[str]
    model: str = MODEL_NAME
    dimensions: int | None = Field(default=1024)


class ServiceState:
    model: BGEM3FlagModel | None = None


state = ServiceState()


@asynccontextmanager
async def lifespan(_: FastAPI):
    state.model = BGEM3FlagModel(MODEL_NAME, use_fp16=False, cache_dir=MODEL_CACHE_DIR)
    yield
    state.model = None


app = FastAPI(title="Local BGE-M3 Embedding Service", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, object]:
    return {"status": "ok" if state.model is not None else "starting", "model": MODEL_NAME}


@app.post("/v1/embeddings")
async def embeddings(request: EmbeddingRequest) -> dict[str, object]:
    if state.model is None:
        raise HTTPException(status_code=503, detail="Embedding model is still loading")
    if request.model not in {MODEL_NAME, "bge-m3"}:
        raise HTTPException(status_code=400, detail="Unsupported embedding model")
    if request.dimensions not in {None, 1024}:
        raise HTTPException(status_code=400, detail="BGE-M3 output dimension is fixed at 1024")
    values = [request.input] if isinstance(request.input, str) else request.input
    if not values or any(not value.strip() for value in values):
        raise HTTPException(status_code=400, detail="input must contain non-empty text")
    encoded = state.model.encode(values, batch_size=BATCH_SIZE, max_length=8192)["dense_vecs"]
    vectors = np.asarray(encoded, dtype=np.float32)
    vectors /= np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12)
    return {
        "object": "list",
        "data": [
            {"object": "embedding", "index": index, "embedding": vector.tolist()}
            for index, vector in enumerate(vectors)
        ],
        "model": "bge-m3",
        "usage": {"prompt_tokens": 0, "total_tokens": 0},
        "created": int(time()),
    }
