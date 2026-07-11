import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.infrastructure.errors import ApplicationError

ALLOWED_EXTENSIONS = {".py", ".java", ".js", ".ts", ".vue", ".md", ".yml", ".yaml", ".sql", ".txt"}
EXCLUDED_PARTS = {".git", "node_modules", ".venv", "venv", "dist", "build", "target", "__pycache__"}


@dataclass(frozen=True)
class GitSnapshot:
    revision: str
    text: str
    files: int


def snapshot_repository(path: str, allowed_root: str | None) -> GitSnapshot:
    if not allowed_root:
        raise ApplicationError(
            "GIT_IMPORT_NOT_CONFIGURED", "Git import root is not configured", status_code=503
        )
    root = Path(allowed_root).resolve()
    repository = Path(path).resolve()
    if repository != root and root not in repository.parents:
        raise ApplicationError(
            "GIT_PATH_BLOCKED", "Repository path is outside import root", status_code=422
        )
    try:
        revision = subprocess.run(
            ["git", "-C", str(repository), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout.strip()
    except (subprocess.SubprocessError, OSError) as exc:
        raise ApplicationError(
            "GIT_READ_FAILED", "Unable to read Git repository", status_code=422
        ) from exc
    sections: list[str] = []
    for file in sorted(repository.rglob("*")):
        relative = file.relative_to(repository)
        if not file.is_file() or file.suffix.lower() not in ALLOWED_EXTENSIONS:
            continue
        if any(part in EXCLUDED_PARTS or part.startswith(".env") for part in relative.parts):
            continue
        if file.stat().st_size > 1024 * 1024:
            continue
        try:
            content = file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        sections.append(f"\n# File: {relative.as_posix()}\n{content}")
    if not sections:
        raise ApplicationError(
            "GIT_CONTENT_EMPTY", "Repository has no supported text files", status_code=422
        )
    return GitSnapshot(revision=revision, text="".join(sections), files=len(sections))
