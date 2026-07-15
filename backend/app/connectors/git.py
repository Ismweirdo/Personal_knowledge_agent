import hashlib
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlparse

from app.infrastructure.errors import ApplicationError
from app.ingestion.cleaning import clean_text

DOCUMENT_EXTENSIONS = {".md", ".txt"}
CONFIG_EXTENSIONS = {".json", ".toml", ".yml", ".yaml"}
CODE_EXTENSIONS = {".py", ".java", ".js", ".ts", ".vue"}
ALLOWED_EXTENSIONS = DOCUMENT_EXTENSIONS | CONFIG_EXTENSIONS | CODE_EXTENSIONS | {".sql"}
EXCLUDED_PARTS = {
    ".git",
    ".github",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
    "target",
    "__pycache__",
    "coverage",
}
EXCLUDED_NAME_PARTS = {
    "lock",
    "八股",
    "面试题",
    "cache",
    "generated",
    "benchmark",
    "load-test",
    "performance",
    "persona",
    "prompt",
    "skill",
    "stress-test",
    "人物",
    "张雪峰",
    "志愿填报",
}
IMPORTANT_DOC_NAMES = {
    "readme.md",
    "项目1设计文档.md",
    "项目1技术文档.md",
    "管理员使用说明.md",
    "上线运行手册.md",
}
IMPORTANT_CONFIG_NAMES = {"package.json", "pyproject.toml", "docker-compose.yml", "Dockerfile"}
GITHUB_ARCHIVE_MAX_BYTES = 80 * 1024 * 1024
GITHUB_ARCHIVE_TIMEOUT_SECONDS = 180
GITHUB_CLONE_TIMEOUT_SECONDS = 90


@dataclass(frozen=True)
class GitSnapshot:
    revision: str
    text: str
    files: int
    locator: str
    display_name: str


def snapshot_repository(path: str, allowed_root: str | None) -> GitSnapshot:
    github_url = normalize_github_url(path)
    if github_url:
        with TemporaryDirectory(prefix="knowledge-agent-git-") as directory:
            repository = Path(directory) / "repo"
            try:
                _clone_github(github_url, repository)
            except ApplicationError as exc:
                if exc.code not in {"GIT_CLONE_TIMEOUT", "GIT_CLONE_FAILED"}:
                    raise
                _download_github_archive(github_url, repository)
            return _snapshot_local_repository(repository, locator=github_url)
    if _looks_like_github_locator(path):
        raise ApplicationError(
            "INVALID_GITHUB_URL",
            "GitHub 仓库地址格式不正确，请填写 https://github.com/用户名/仓库名",
            status_code=422,
        )
    return _snapshot_allowed_local_repository(path, allowed_root)


def _snapshot_allowed_local_repository(path: str, allowed_root: str | None) -> GitSnapshot:
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
    return _snapshot_local_repository(repository, locator=str(repository))


def _snapshot_local_repository(repository: Path, *, locator: str) -> GitSnapshot:
    revision: str | None = None
    try:
        revision = subprocess.run(
            ["git", "-C", str(repository), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        revision = None
    sections: list[str] = []
    docs: list[Path] = []
    configs: list[Path] = []
    code_files: list[Path] = []
    for file in sorted(repository.rglob("*")):
        relative = file.relative_to(repository)
        if not _is_relevant_file(file, relative):
            continue
        if file.suffix.lower() in DOCUMENT_EXTENSIONS:
            docs.append(file)
        elif file.name in IMPORTANT_CONFIG_NAMES or file.suffix.lower() in CONFIG_EXTENSIONS:
            configs.append(file)
        elif file.suffix.lower() in CODE_EXTENSIONS:
            code_files.append(file)
    sections.append(_project_header(repository, locator, revision or "archive"))
    sections.extend(_document_sections(repository, docs))
    sections.extend(_config_sections(repository, configs))
    code_summary = _code_summary(repository, code_files)
    if code_summary:
        sections.append(code_summary)
    if not sections:
        raise ApplicationError(
            "GIT_CONTENT_EMPTY", "Repository has no supported text files", status_code=422
        )
    text = clean_text("\n\n".join(sections))
    if not text:
        raise ApplicationError(
            "GIT_CONTENT_EMPTY", "Repository has no supported text files", status_code=422
        )
    if revision is None:
        revision = hashlib.sha256(text.encode()).hexdigest()
    return GitSnapshot(
        revision=revision,
        text=text,
        files=len(docs) + len(configs) + len(code_files),
        locator=locator,
        display_name=_display_name(repository, locator),
    )


def _clone_github(url: str, target: Path) -> None:
    try:
        result = subprocess.run(
            ["git", "clone", "--depth", "1", "--filter=blob:limit=1m", url, str(target)],
            capture_output=True,
            text=True,
            check=False,
            timeout=GITHUB_CLONE_TIMEOUT_SECONDS,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except subprocess.TimeoutExpired as exc:
        raise ApplicationError(
            "GIT_CLONE_TIMEOUT",
            "GitHub 仓库克隆超时，请稍后重试或检查仓库体积",
            status_code=504,
        ) from exc
    except OSError as exc:
        raise ApplicationError(
            "GIT_CLONE_UNAVAILABLE",
            "服务器无法执行 Git 克隆，请检查 Git 是否已安装",
            status_code=503,
        ) from exc
    if result.returncode == 0:
        return
    error = (result.stderr or result.stdout or "").lower()
    if any(
        marker in error
        for marker in (
            "repository not found",
            "authentication failed",
            "could not read username",
            "terminal prompts disabled",
        )
    ):
        message = "找不到该 GitHub 仓库，或仓库为私有仓库且当前未授权"
    elif any(
        marker in error
        for marker in ("could not resolve host", "failed to connect", "connection timed out")
    ):
        message = "服务器暂时无法连接 GitHub，请检查网络后重试"
    else:
        message = "GitHub 仓库克隆失败，请确认地址指向可访问的代码仓库"
    raise ApplicationError("GIT_CLONE_FAILED", message, status_code=422)


def _download_github_archive(url: str, target: Path) -> None:
    owner, repository = _github_owner_repository(url)
    errors: list[str] = []
    with TemporaryDirectory(prefix="knowledge-agent-archive-") as directory:
        archive_path = Path(directory) / "repo.zip"
        extract_root = Path(directory) / "extract"
        for branch in _default_branch_candidates(owner, repository):
            archive_url = (
                f"https://codeload.github.com/{owner}/{repository}/zip/refs/heads/{branch}"
            )
            try:
                _download_file(archive_url, archive_path)
                _extract_zip(archive_path, extract_root)
                roots = [item for item in extract_root.iterdir() if item.is_dir()]
                if not roots:
                    raise ApplicationError(
                        "GITHUB_ARCHIVE_EMPTY",
                        "GitHub 仓库压缩包为空，请确认仓库内容",
                        status_code=422,
                    )
                shutil.copytree(roots[0], target)
                return
            except ApplicationError as exc:
                errors.append(exc.message)
                shutil.rmtree(extract_root, ignore_errors=True)
                archive_path.unlink(missing_ok=True)
        raise ApplicationError(
            "GITHUB_ARCHIVE_DOWNLOAD_FAILED",
            "服务器无法下载 GitHub 仓库压缩包，请稍后重试或检查仓库是否公开",
            status_code=504,
            details={"attempts": errors[-3:]},
        )


def _download_file(url: str, target: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "Laylight-Agent/0.1"})
    try:
        with urllib.request.urlopen(
            request, timeout=GITHUB_ARCHIVE_TIMEOUT_SECONDS
        ) as response:
            length = response.headers.get("Content-Length")
            if length and int(length) > GITHUB_ARCHIVE_MAX_BYTES:
                raise ApplicationError(
                    "GITHUB_ARCHIVE_TOO_LARGE",
                    "GitHub 仓库压缩包过大，请改用服务器本地路径导入",
                    status_code=413,
                )
            total = 0
            with target.open("wb") as output:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > GITHUB_ARCHIVE_MAX_BYTES:
                        raise ApplicationError(
                            "GITHUB_ARCHIVE_TOO_LARGE",
                            "GitHub 仓库压缩包过大，请改用服务器本地路径导入",
                            status_code=413,
                        )
                    output.write(chunk)
    except TimeoutError as exc:
        raise ApplicationError(
            "GITHUB_ARCHIVE_TIMEOUT",
            "GitHub 仓库压缩包下载超时，请稍后重试",
            status_code=504,
        ) from exc
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise ApplicationError(
                "GITHUB_ARCHIVE_NOT_FOUND",
                "找不到该 GitHub 仓库或默认分支",
                status_code=422,
            ) from exc
        raise ApplicationError(
            "GITHUB_ARCHIVE_DOWNLOAD_FAILED",
            "GitHub 仓库压缩包下载失败",
            status_code=504,
        ) from exc
    except urllib.error.URLError as exc:
        raise ApplicationError(
            "GITHUB_ARCHIVE_DOWNLOAD_FAILED",
            "服务器暂时无法连接 GitHub 压缩包下载服务",
            status_code=504,
        ) from exc


def _extract_zip(archive_path: Path, extract_root: Path) -> None:
    extract_root.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(archive_path) as archive:
            for member in archive.infolist():
                destination = (extract_root / member.filename).resolve()
                if (
                    extract_root.resolve() not in destination.parents
                    and destination != extract_root
                ):
                    raise ApplicationError(
                        "GITHUB_ARCHIVE_INVALID",
                        "GitHub 仓库压缩包路径不安全",
                        status_code=422,
                    )
            archive.extractall(extract_root)
    except zipfile.BadZipFile as exc:
        raise ApplicationError(
            "GITHUB_ARCHIVE_INVALID",
            "GitHub 仓库压缩包无法解析",
            status_code=422,
        ) from exc


def _default_branch_candidates(owner: str, repository: str) -> list[str]:
    branches: list[str] = []
    request = urllib.request.Request(
        f"https://api.github.com/repos/{owner}/{repository}",
        headers={"User-Agent": "Laylight-Agent/0.1", "Accept": "application/vnd.github+json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8")
            match = re.search(r'"default_branch"\s*:\s*"([^"]+)"', body)
            if match:
                branches.append(match.group(1))
    except (TimeoutError, urllib.error.URLError, UnicodeDecodeError):
        pass
    branches.extend(["main", "master"])
    return list(dict.fromkeys(branches))


def _github_owner_repository(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        raise ApplicationError(
            "INVALID_GITHUB_URL",
            "GitHub 仓库地址格式不正确，请填写 https://github.com/用户名/仓库名",
            status_code=422,
        )
    return parts[0], re.sub(r"\.git$", "", parts[1], flags=re.I)


def normalize_github_url(value: str) -> str | None:
    """Return one canonical HTTPS repository URL for common GitHub copy formats."""
    candidate = value.strip()
    if not candidate:
        return None
    ssh_match = re.fullmatch(r"git@github\.com:([^/]+)/([^/]+?)(?:\.git)?/?", candidate, re.I)
    if ssh_match:
        owner, repository = ssh_match.groups()
        return f"https://github.com/{owner}/{repository}"
    if re.match(r"^(?:www\.)?github\.com/", candidate, re.I):
        candidate = f"https://{candidate}"
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() not in {
        "github.com",
        "www.github.com",
    }:
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        return None
    owner, repository = parts[:2]
    repository = re.sub(r"\.git$", "", repository, flags=re.I)
    component = re.compile(r"^[A-Za-z0-9_.-]+$")
    if (
        not owner
        or not repository
        or not component.fullmatch(owner)
        or not component.fullmatch(repository)
    ):
        return None
    return f"https://github.com/{owner}/{repository}"


def _looks_like_github_locator(value: str) -> bool:
    lower = value.strip().lower()
    return "github.com" in lower or lower.startswith("git@github.com:")


def _is_github_url(value: str) -> bool:
    return normalize_github_url(value) is not None


def _is_relevant_file(file: Path, relative: Path) -> bool:
    if not file.is_file() or file.suffix.lower() not in ALLOWED_EXTENSIONS:
        return False
    parts = {part.lower() for part in relative.parts}
    name = file.name.lower()
    path_text = relative.as_posix().lower()
    if any(part in EXCLUDED_PARTS or part.startswith(".env") for part in parts):
        return False
    if any(value in path_text for value in EXCLUDED_NAME_PARTS):
        return False
    if "test" in parts or "tests" in parts or name.startswith("test_") or name.endswith(".test.ts"):
        return False
    if name.endswith((".lock", ".min.js", ".map")):
        return False
    return file.stat().st_size <= 512 * 1024


def _project_header(repository: Path, locator: str, revision: str) -> str:
    return (
        f"# 项目资料卡\n"
        f"- 项目名称：{_display_name(repository, locator)}\n"
        f"- 来源：{locator}\n"
        f"- Git revision：{revision[:12]}\n"
        "- 说明：以下内容已过滤依赖、测试、构建产物、密钥文件和泛化学习资料。"
    )


def _document_sections(repository: Path, docs: list[Path]) -> list[str]:
    selected = [
        file for file in sorted(docs, key=lambda file: _doc_rank(repository, file))
        if _doc_rank(repository, file)[0] < 4
    ][:8]
    sections: list[str] = []
    seen: set[str] = set()
    for file in selected:
        content = _read_clean(file, max_chars=8000)
        signature = re.sub(r"\s+", " ", content).strip()
        if content and signature not in seen:
            seen.add(signature)
            sections.append(f"# 项目文档：{file.relative_to(repository).as_posix()}\n{content}")
    return sections


def _config_sections(repository: Path, configs: list[Path]) -> list[str]:
    selected = sorted(configs, key=lambda file: _config_rank(file))[:8]
    sections: list[str] = []
    for file in selected:
        content = _read_clean(file, max_chars=4000)
        if content:
            sections.append(f"# 项目配置摘要：{file.relative_to(repository).as_posix()}\n{content}")
    return sections


def _code_summary(repository: Path, code_files: list[Path]) -> str:
    selected = sorted(code_files, key=lambda file: (len(file.parts), file.as_posix()))[:80]
    lines = ["# 代码结构摘要", "以下是用于理解项目职责和技术栈的结构化摘要，不包含完整源码。"]
    for file in selected:
        relative = file.relative_to(repository).as_posix()
        text = _read_clean(file, max_chars=10000)
        if not text:
            continue
        symbols = _extract_symbols(text)
        signals = _tech_signals(text)
        summary = f"- {relative}"
        if signals:
            summary += f"；技术信号：{', '.join(signals[:8])}"
        if symbols:
            summary += f"；主要结构：{', '.join(symbols[:10])}"
        lines.append(summary)
    return "\n".join(lines) if len(lines) > 2 else ""


def _extract_symbols(text: str) -> list[str]:
    patterns = [
        r"^\s*class\s+([A-Za-z_][\w]*)",
        r"^\s*(?:async\s+)?def\s+([A-Za-z_][\w]*)",
        r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_][\w]*)",
        r"^\s*(?:const|let|var)\s+([A-Za-z_][\w]*)\s*=",
    ]
    values: list[str] = []
    for pattern in patterns:
        values.extend(re_match for re_match in re.findall(pattern, text, flags=re.M))
    return list(dict.fromkeys(values))


def _tech_signals(text: str) -> list[str]:
    known = [
        "FastAPI",
        "Vue",
        "PostgreSQL",
        "pgvector",
        "Redis",
        "Docker",
        "SQLAlchemy",
        "Alembic",
        "DeepSeek",
        "OpenAI",
        "SSE",
        "JWT",
        "pytest",
    ]
    lower = text.lower()
    return [item for item in known if item.lower() in lower]


def _read_clean(file: Path, *, max_chars: int) -> str:
    try:
        return clean_text(file.read_text(encoding="utf-8"))[:max_chars].strip()
    except UnicodeDecodeError:
        return ""


def _doc_rank(repository: Path, file: Path) -> tuple[int, str]:
    relative = file.relative_to(repository).as_posix().lower()
    name = file.name.lower()
    if name in IMPORTANT_DOC_NAMES:
        return (0, relative)
    if "readme" in name or "设计" in name or "技术" in name or "架构" in name or "说明" in name:
        return (1, relative)
    return (4, relative)


def _config_rank(file: Path) -> tuple[int, str]:
    name = file.name
    return (0 if name in IMPORTANT_CONFIG_NAMES else 2, file.as_posix())


def _display_name(repository: Path, locator: str) -> str:
    if _is_github_url(locator):
        return Path(urlparse(locator).path).stem
    return repository.name
