import hashlib
import json
import unicodedata

from pydantic import AliasChoices, BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.errors import ApplicationError
from app.infrastructure.llm import ChatModelClient
from app.infrastructure.models import (
    DocumentChunk,
    KnowledgeEntity,
    KnowledgeEvidence,
    KnowledgeRelation,
)


class EntityCandidate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    entity_type: str = Field(
        min_length=1,
        max_length=50,
        validation_alias=AliasChoices("entity_type", "type"),
    )
    summary: str | None = Field(default=None, max_length=2000)
    confidence: float = Field(ge=0, le=1)


class RelationCandidate(BaseModel):
    source: str = Field(
        min_length=1, max_length=200, validation_alias=AliasChoices("source", "from")
    )
    predicate: str = Field(
        min_length=1,
        max_length=100,
        validation_alias=AliasChoices("predicate", "type"),
    )
    target: str = Field(min_length=1, max_length=200, validation_alias=AliasChoices("target", "to"))
    confidence: float = Field(ge=0, le=1)


class ExtractionResult(BaseModel):
    entities: list[EntityCandidate] = Field(default_factory=list, max_length=100)
    relations: list[RelationCandidate] = Field(default_factory=list, max_length=200)


def parse_extraction(content: str) -> ExtractionResult:
    try:
        value = content.strip()
        if value.startswith("```"):
            lines = value.splitlines()
            value = "\n".join(lines[1:-1]).strip()
        start, end = value.find("{"), value.rfind("}")
        if start < 0 or end < start:
            raise json.JSONDecodeError("No JSON object", value, 0)
        return ExtractionResult.model_validate(json.loads(value[start : end + 1]))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ApplicationError(
            "GRAPH_EXTRACTION_INVALID",
            "Knowledge extraction returned invalid structured data",
            status_code=502,
        ) from exc


def normalize_name(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


class GraphExtractionService:
    def __init__(self, session: AsyncSession, chat: ChatModelClient) -> None:
        self.session = session
        self.chat = chat

    async def extract_chunk(self, user_id: str, chunk_id: str) -> dict[str, int]:
        chunk = await self.session.scalar(
            select(DocumentChunk).where(
                DocumentChunk.id == chunk_id, DocumentChunk.user_id == user_id
            )
        )
        if chunk is None:
            raise ApplicationError("CHUNK_NOT_FOUND", "Document chunk not found", status_code=404)
        prompt = (
            "Extract entities and factual relations. Return JSON only with entities and "
            "relations arrays. Entity fields: name, entity_type, summary, confidence. "
            "Relation fields: source, predicate, target, confidence. "
            "Every item needs confidence 0..1.\n<context>" + chunk.content + "</context>"
        )
        result = parse_extraction(
            await self.chat.complete(
                [
                    {
                        "role": "system",
                        "content": "You extract evidence-backed personal knowledge.",
                    },
                    {"role": "user", "content": prompt},
                ],
                json_mode=True,
            )
        )
        entities: dict[str, KnowledgeEntity] = {}
        for item in result.entities:
            key = normalize_name(item.name)
            entity = await self.session.scalar(
                select(KnowledgeEntity).where(
                    KnowledgeEntity.kb_id == chunk.kb_id,
                    KnowledgeEntity.entity_type == item.entity_type.upper(),
                    KnowledgeEntity.normalized_name == key,
                )
            )
            if entity is None:
                entity = KnowledgeEntity(
                    user_id=user_id,
                    kb_id=chunk.kb_id,
                    canonical_name=item.name,
                    normalized_name=key,
                    entity_type=item.entity_type.upper(),
                    summary=item.summary,
                    confidence=item.confidence,
                    extractor_version=self.chat.model,
                )
                self.session.add(entity)
                await self.session.flush()
            entities[key] = entity
            await self._evidence(chunk, entity_id=entity.id)
        relation_count = 0
        for item in result.relations:
            source, target = (
                entities.get(normalize_name(item.source)),
                entities.get(normalize_name(item.target)),
            )
            if source is None or target is None:
                continue
            relation = await self.session.scalar(
                select(KnowledgeRelation).where(
                    KnowledgeRelation.kb_id == chunk.kb_id,
                    KnowledgeRelation.source_entity_id == source.id,
                    KnowledgeRelation.predicate == item.predicate,
                    KnowledgeRelation.target_entity_id == target.id,
                )
            )
            if relation is None:
                relation = KnowledgeRelation(
                    user_id=user_id,
                    kb_id=chunk.kb_id,
                    source_entity_id=source.id,
                    predicate=item.predicate,
                    target_entity_id=target.id,
                    confidence=item.confidence,
                    extractor_version=self.chat.model,
                )
                self.session.add(relation)
                await self.session.flush()
            await self._evidence(chunk, relation_id=relation.id)
            relation_count += 1
        await self.session.commit()
        return {"entities": len(entities), "relations": relation_count}

    async def _evidence(
        self, chunk: DocumentChunk, *, entity_id: str | None = None, relation_id: str | None = None
    ) -> None:
        exists = await self.session.scalar(
            select(KnowledgeEvidence.id).where(
                KnowledgeEvidence.chunk_id == chunk.id,
                KnowledgeEvidence.entity_id == entity_id,
                KnowledgeEvidence.relation_id == relation_id,
            )
        )
        if exists is None:
            self.session.add(
                KnowledgeEvidence(
                    user_id=chunk.user_id,
                    kb_id=chunk.kb_id,
                    entity_id=entity_id,
                    relation_id=relation_id,
                    source_version_id=chunk.source_version_id,
                    chunk_id=chunk.id,
                    locator=str(chunk.chunk_metadata or {}),
                    quote_hash=hashlib.sha256(chunk.content.encode()).hexdigest(),
                )
            )
