import pytest

from app.infrastructure.errors import ApplicationError
from app.knowledge_graph.extraction import parse_extraction


def test_parse_structured_graph_candidates() -> None:
    result = parse_extraction(
        '{"entities":[{"name":"FastAPI","entity_type":"TECHNOLOGY","confidence":0.95}],'
        '"relations":[]}'
    )
    assert result.entities[0].name == "FastAPI"
    assert result.entities[0].confidence == 0.95


@pytest.mark.parametrize(
    "payload",
    ["not-json", '{"entities":[{"name":"","entity_type":"TECH","confidence":2}]}'],
)
def test_invalid_graph_candidates_are_rejected(payload: str) -> None:
    with pytest.raises(ApplicationError) as exc_info:
        parse_extraction(payload)
    assert exc_info.value.code == "GRAPH_EXTRACTION_INVALID"
