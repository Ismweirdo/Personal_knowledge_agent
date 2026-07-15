import subprocess

import anyio
import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.connectors.git import normalize_github_url, snapshot_repository
from app.connectors.web import WebSnapshot, fetch_web, validate_public_url
from app.infrastructure.config import Settings
from app.infrastructure.errors import ApplicationError
from app.infrastructure.models import Base, KnowledgeBase, User
from app.ingestion.sync import SourceSyncService


@pytest.mark.parametrize(
    "url", ["http://127.0.0.1/private", "http://localhost/admin", "file:///etc/passwd"]
)
def test_web_connector_blocks_non_public_targets(url: str) -> None:
    with pytest.raises(ApplicationError):
        validate_public_url(url)


@pytest.mark.asyncio
async def test_web_connector_extracts_text_and_supports_not_modified() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.headers.get("if-none-match") == '"v1"':
            return httpx.Response(304)
        return httpx.Response(
            200,
            text="<html><script>bad()</script><body>Learning FastAPI</body></html>",
            headers={"etag": '"v1"'},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        snapshot = await fetch_web("https://example.com/notes", client=client)
        unchanged = await fetch_web("https://example.com/notes", etag='"v1"', client=client)

    assert snapshot is not None
    assert snapshot.text == "Learning FastAPI"
    assert snapshot.etag == '"v1"'
    assert unchanged is None


def test_git_snapshot_excludes_secrets_and_dependencies(tmp_path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    subprocess.run(["git", "init"], cwd=repository, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repository, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repository, check=True)
    (repository / "README.md").write_text("Project knowledge", encoding="utf-8")
    (repository / ".env").write_text("SECRET=hidden", encoding="utf-8")
    dependencies = repository / "node_modules"
    dependencies.mkdir()
    (dependencies / "package.js").write_text("ignored", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repository, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"], cwd=repository, check=True, capture_output=True
    )

    snapshot = snapshot_repository(str(repository), str(tmp_path))

    assert snapshot.files == 1
    assert "Project knowledge" in snapshot.text
    assert "SECRET" not in snapshot.text
    assert len(snapshot.revision) == 40


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (
            "https://github.com/Ismweirdo/Personal_knowledge_agent.git",
            "https://github.com/Ismweirdo/Personal_knowledge_agent",
        ),
        (
            "https://github.com/Ismweirdo/Personal_knowledge_agent/tree/main/backend",
            "https://github.com/Ismweirdo/Personal_knowledge_agent",
        ),
        (
            "github.com/Ismweirdo/Personal_knowledge_agent",
            "https://github.com/Ismweirdo/Personal_knowledge_agent",
        ),
        (
            "git@github.com:Ismweirdo/Personal_knowledge_agent.git",
            "https://github.com/Ismweirdo/Personal_knowledge_agent",
        ),
    ],
)
def test_normalize_github_repository_urls(value: str, expected: str) -> None:
    assert normalize_github_url(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "https://gitlab.com/owner/repository",
        "https://github.com/owner",
        "not-a-repository",
    ],
)
def test_normalize_github_repository_url_rejects_invalid_values(value: str) -> None:
    assert normalize_github_url(value) is None


@pytest.mark.asyncio
async def test_git_sync_reuses_unchanged_revision(tmp_path) -> None:
    repository = tmp_path / "repo"
    await anyio.to_thread.run_sync(create_test_repository, repository)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        admin = User(email="admin@example.com", password_hash="unused", role="ADMIN")
        session.add(admin)
        await session.flush()
        kb = KnowledgeBase(user_id=admin.id, name="Projects")
        session.add(kb)
        await session.commit()
        settings = Settings(
            git_import_root=str(tmp_path),
            file_storage_path=str(tmp_path / "uploads"),
            _env_file=None,
        )
        service = SourceSyncService(session, settings)

        first = await service.sync_git(admin.id, kb.id, str(repository))
        repeated = await service.sync_git(admin.id, kb.id, str(repository))

        assert first.status == "PARSED"
        assert repeated.version_id == first.version_id
        assert repeated.unchanged is True
    await engine.dispose()


@pytest.mark.asyncio
async def test_web_sync_reuses_not_modified_version(tmp_path, monkeypatch) -> None:
    calls = 0

    async def fake_fetch(url: str, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            return None
        return WebSnapshot(url=url, text="Personal learning notes", etag='"v1"', last_modified=None)

    monkeypatch.setattr("app.ingestion.sync.fetch_web", fake_fetch)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        admin = User(email="web-admin@example.com", password_hash="unused", role="ADMIN")
        session.add(admin)
        await session.flush()
        kb = KnowledgeBase(user_id=admin.id, name="Web")
        session.add(kb)
        await session.commit()
        settings = Settings(file_storage_path=str(tmp_path / "uploads"), _env_file=None)
        service = SourceSyncService(session, settings)

        first = await service.sync_web(admin.id, kb.id, "https://example.com/notes")
        repeated = await service.sync_web(admin.id, kb.id, "https://example.com/notes")

        assert first.chunk_count == 1
        assert repeated.version_id == first.version_id
        assert repeated.unchanged is True
    await engine.dispose()


def create_test_repository(repository) -> None:
    repository.mkdir()
    subprocess.run(["git", "init"], cwd=repository, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repository, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repository, check=True)
    (repository / "README.md").write_text("Knowledge snapshot", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repository, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"], cwd=repository, check=True, capture_output=True
    )
