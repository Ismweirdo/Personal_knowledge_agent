from dataclasses import dataclass
from pathlib import Path

import fitz

from app.infrastructure.errors import ApplicationError
from app.ingestion.cleaning import clean_text

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
                ParsedPage(clean_text(page.get_text()), index + 1)
                for index, page in enumerate(document)
            ]
    else:
        pages = [ParsedPage(clean_text(path.read_text(encoding="utf-8")))]
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
        paragraphs = [item.strip() for item in re_split_paragraphs(page.text) if item.strip()]
        current: list[str] = []
        current_len = 0
        start = 0
        for paragraph in paragraphs:
            parts = (
                _split_long_paragraph(paragraph, max_chars=max_chars, overlap=overlap)
                if len(paragraph) > max_chars
                else [paragraph]
            )
            for part in parts:
                if len(part) >= max_chars and not current:
                    chunks.append({"content": part, "page": page.page, "char_start": start})
                    start += max(1, len(part) - overlap)
                    continue
                if current and current_len + len(part) + 2 > max_chars:
                    content = "\n\n".join(current).strip()
                    chunks.append({"content": content, "page": page.page, "char_start": start})
                    overlap_text = content[-overlap:] if overlap > 0 else ""
                    current = [overlap_text, part] if overlap_text else [part]
                    current_len = sum(len(item) for item in current) + 2 * (len(current) - 1)
                    start = max(0, start + len(content) - len(overlap_text))
                else:
                    current.append(part)
                    current_len += len(part) + 2
        if current:
            chunks.append(
                {"content": "\n\n".join(current).strip(), "page": page.page, "char_start": start}
            )
    return chunks


def _split_long_paragraph(text: str, *, max_chars: int, overlap: int) -> list[str]:
    parts: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        parts.append(text[start:end])
        if end == len(text):
            break
        start = max(0, end - overlap)
    return parts


def re_split_paragraphs(text: str) -> list[str]:
    import re

    return re.split(r"\n\s*\n|(?<=。)\s+|(?<=；)\s+|(?<=\.)\s{2,}", text)
