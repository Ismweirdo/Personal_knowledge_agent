import re
from collections import Counter
from pathlib import Path

BOILERPLATE_PATTERNS = [
    re.compile(r"^\s*目录\s*$"),
    re.compile(r"^\s*table of contents\s*$", re.I),
    re.compile(r"^\s*第\s*\d+\s*页\s*/\s*共\s*\d+\s*页\s*$"),
    re.compile(r"^\s*page\s+\d+(\s+of\s+\d+)?\s*$", re.I),
]


def clean_text(value: str, *, max_blank_lines: int = 1) -> str:
    """Normalize user-provided knowledge before chunking.

    The goal is not to rewrite facts, but to remove obvious extraction noise:
    repeated whitespace, page boilerplate, empty table-of-contents headings,
    and duplicate adjacent lines commonly produced by PDFs.
    """

    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[\u200b-\u200f\ufeff]", "", value)
    lines = [_normalize_line(line) for line in value.split("\n")]

    counts = Counter(line for line in lines if len(line) >= 8)
    cleaned: list[str] = []
    blank_count = 0
    previous = ""
    for line in lines:
        if any(pattern.match(line) for pattern in BOILERPLATE_PATTERNS):
            continue
        if line and counts[line] > 4 and len(line) < 80:
            continue
        if line == previous and line:
            continue
        if not line:
            blank_count += 1
            if blank_count <= max_blank_lines:
                cleaned.append("")
            previous = line
            continue
        blank_count = 0
        cleaned.append(line)
        previous = line
    text = "\n".join(cleaned).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def clean_title(value: str) -> str:
    value = Path(value).name.strip()
    return re.sub(r"[_\-]+", " ", value).strip() or "未命名资料"


def _normalize_line(line: str) -> str:
    line = re.sub(r"[ \t]+", " ", line).strip()
    line = re.sub(r"\s+([,.;:!?，。；：！？])", r"\1", line)
    return line
