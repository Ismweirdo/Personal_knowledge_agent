from dataclasses import dataclass
from pathlib import Path

import fitz

from app.infrastructure.errors import ApplicationError

ALLOWED_EXTENSIONS = {".pdf", ".md", ".txt"}


@dataclass(frozen=True)
class ParsedPage:
    text: str
    page: int | None = None


def parse_document(path: Path, original_name: str) -> list[ParsedPage]:
    extension = Path(original_name).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise ApplicationError(
            "UNSUPPORTED_DOCUMENT_TYPE", "Unsupported document type", status_code=415
        )
    if extension == ".pdf":
        with fitz.open(path) as document:
            pages = [
                ParsedPage(page.get_text().strip(), index + 1)
                for index, page in enumerate(document)
            ]
    else:
        pages = [ParsedPage(path.read_text(encoding="utf-8").strip())]
    if not any(page.text for page in pages):
        raise ApplicationError(
            "DOCUMENT_EMPTY", "Document contains no extractable text", status_code=422
        )
    return pages


def chunk_pages(
    pages: list[ParsedPage], max_chars: int = 2400, overlap: int = 300
) -> list[dict[str, object]]:
    if overlap >= max_chars:
        raise ValueError("overlap must be smaller than max_chars")
    chunks: list[dict[str, object]] = []
    for page in pages:
        text = " ".join(page.text.split())
        start = 0
        while start < len(text):
            end = min(start + max_chars, len(text))
            content = text[start:end]
            chunks.append({"content": content, "page": page.page, "char_start": start})
            if end == len(text):
                break
            start = end - overlap
    return chunks
