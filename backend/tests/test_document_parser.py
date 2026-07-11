from pathlib import Path

import pytest

from app.infrastructure.errors import ApplicationError
from app.ingestion.parser import ParsedPage, chunk_pages, parse_document


def test_parse_and_chunk_text(tmp_path: Path) -> None:
    document = tmp_path / "notes.md"
    document.write_text("FastAPI async programming\n\nPostgreSQL and pgvector", encoding="utf-8")

    pages = parse_document(document, document.name)
    chunks = chunk_pages(pages, max_chars=30, overlap=5)

    assert pages[0].page is None
    assert len(chunks) >= 2
    assert chunks[0]["content"].startswith("FastAPI")


def test_chunk_overlap_preserves_context() -> None:
    chunks = chunk_pages([ParsedPage("0123456789abcdef")], max_chars=10, overlap=3)

    assert chunks[0]["content"][-3:] == chunks[1]["content"][:3]


def test_unsupported_document_is_rejected(tmp_path: Path) -> None:
    document = tmp_path / "secret.env"
    document.write_text("KEY=value", encoding="utf-8")

    with pytest.raises(ApplicationError) as exc_info:
        parse_document(document, document.name)

    assert exc_info.value.code == "UNSUPPORTED_DOCUMENT_TYPE"
