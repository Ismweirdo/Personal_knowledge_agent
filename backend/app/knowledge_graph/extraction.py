import json

from pydantic import BaseModel, Field, ValidationError

from app.infrastructure.errors import ApplicationError


class EntityCandidate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    entity_type: str = Field(min_length=1, max_length=50)
    summary: str | None = Field(default=None, max_length=2000)
    confidence: float = Field(ge=0, le=1)


class RelationCandidate(BaseModel):
    source: str = Field(min_length=1, max_length=200)
    predicate: str = Field(min_length=1, max_length=100)
    target: str = Field(min_length=1, max_length=200)
    confidence: float = Field(ge=0, le=1)


class ExtractionResult(BaseModel):
    entities: list[EntityCandidate] = Field(default_factory=list, max_length=100)
    relations: list[RelationCandidate] = Field(default_factory=list, max_length=200)


def parse_extraction(content: str) -> ExtractionResult:
    try:
        return ExtractionResult.model_validate(json.loads(content))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ApplicationError(
            "GRAPH_EXTRACTION_INVALID",
            "Knowledge extraction returned invalid structured data",
            status_code=502,
        ) from exc
