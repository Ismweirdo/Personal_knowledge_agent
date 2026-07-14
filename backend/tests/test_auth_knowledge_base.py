from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.infrastructure.config import Settings, get_settings
from app.infrastructure.database import get_session
from app.infrastructure.embedding import get_embedding_client
from app.infrastructure.models import Base, User
from app.infrastructure.security import password_hash
from app.main import create_app


class FakeEmbeddingClient:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * 1536 for _ in texts]


@pytest_asyncio.fixture
async def client(tmp_path) -> AsyncIterator[AsyncClient]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with session_factory() as seed_session:
        seed_session.add(
            User(
                email="admin@example.com",
                password_hash=password_hash.hash("secure-password"),
                role="ADMIN",
            )
        )
        await seed_session.commit()

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_settings] = lambda: Settings(
        jwt_secret="test-secret-that-is-long-enough",
        file_storage_path=str(tmp_path / "uploads"),
        admin_username="laylight",
        admin_password="admin-password",
        visitor_access_key="test-visitor-key",
        _env_file=None,
    )
    app.dependency_overrides[get_embedding_client] = lambda: FakeEmbeddingClient()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as value:
        yield value
    await engine.dispose()


async def register(client: AsyncClient, email: str) -> str:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "secure-password"},
    )
    assert response.status_code == 201
    return response.json()["access_token"]


async def admin_token(client: AsyncClient) -> str:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "secure-password"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


async def visitor_token(client: AsyncClient) -> str:
    response = await client.post("/api/v1/auth/access", json={"access_key": "test-visitor-key"})
    assert response.status_code == 200
    return response.json()["access_token"]


@pytest.mark.asyncio
async def test_register_login_and_duplicate_email(client: AsyncClient) -> None:
    token = await register(client, "user@example.com")
    assert token

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "USER@example.com", "password": "secure-password"},
    )
    assert login.status_code == 200
    me = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert me.json()["role"] == "USER"

    duplicate = await client.post(
        "/api/v1/auth/register",
        json={"email": "user@example.com", "password": "secure-password"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "EMAIL_ALREADY_EXISTS"


@pytest.mark.asyncio
async def test_admin_login_and_visitor_access(client: AsyncClient) -> None:
    invalid_access = await client.post("/api/v1/auth/access", json={"access_key": "bad"})
    assert invalid_access.status_code == 401
    assert invalid_access.json()["code"] == "INVALID_ACCESS_KEY"

    visitor = await client.post("/api/v1/auth/access", json={"access_key": "test-visitor-key"})
    assert visitor.status_code == 200
    visitor_me = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {visitor.json()['access_token']}"},
    )
    assert visitor_me.json()["role"] == "USER"

    invalid_admin = await client.post(
        "/api/v1/auth/admin/login",
        json={"username": "laylight", "password": "wrong"},
    )
    assert invalid_admin.status_code == 401

    admin = await client.post(
        "/api/v1/auth/admin/login",
        json={"username": "laylight", "password": "admin-password"},
    )
    assert admin.status_code == 200
    admin_me = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {admin.json()['access_token']}"},
    )
    assert admin_me.json()["email"] == "laylight@example.com"
    assert admin_me.json()["role"] == "ADMIN"


@pytest.mark.asyncio
async def test_knowledge_bases_require_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/knowledge-bases")
    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_REQUIRED"


@pytest.mark.asyncio
async def test_knowledge_base_crud_and_user_isolation(client: AsyncClient) -> None:
    first_token = await admin_token(client)
    second_token = await register(client, "second@example.com")
    first_headers = {"Authorization": f"Bearer {first_token}"}
    second_headers = {"Authorization": f"Bearer {second_token}"}

    created = await client.post(
        "/api/v1/knowledge-bases",
        headers=first_headers,
        json={"name": "Notes", "description": "Personal notes", "is_published": True},
    )
    assert created.status_code == 201
    knowledge_base_id = created.json()["id"]

    public_agent = await client.get("/api/v1/agent")
    assert public_agent.status_code == 200
    assert public_agent.json()["knowledgeBaseId"] == knowledge_base_id

    listed = await client.get("/api/v1/knowledge-bases", headers=first_headers)
    assert [item["id"] for item in listed.json()] == [knowledge_base_id]

    forbidden_as_not_found = await client.patch(
        f"/api/v1/knowledge-bases/{knowledge_base_id}",
        headers=second_headers,
        json={"name": "Stolen"},
    )
    assert forbidden_as_not_found.status_code == 403
    assert forbidden_as_not_found.json()["code"] == "ADMIN_REQUIRED"

    user_create = await client.post(
        "/api/v1/knowledge-bases",
        headers=second_headers,
        json={"name": "User agent"},
    )
    assert user_create.status_code == 403

    deleted = await client.delete(
        f"/api/v1/knowledge-bases/{knowledge_base_id}", headers=first_headers
    )
    assert deleted.status_code == 204


@pytest.mark.asyncio
async def test_document_upload_is_idempotent_and_user_isolated(client: AsyncClient) -> None:
    owner_token = await admin_token(client)
    other_token = await register(client, "other@example.com")
    owner_headers = {"Authorization": f"Bearer {owner_token}"}
    other_headers = {"Authorization": f"Bearer {other_token}"}
    knowledge_base = await client.post(
        "/api/v1/knowledge-bases",
        headers=owner_headers,
        json={"name": "Learning"},
    )
    knowledge_base_id = knowledge_base.json()["id"]
    document = (
        "notes.md",
        b"FastAPI uses async Python.\nPostgreSQL stores knowledge.",
        "text/markdown",
    )

    first = await client.post(
        f"/api/v1/knowledge-bases/{knowledge_base_id}/documents",
        headers=owner_headers,
        files={"file": document},
    )
    assert first.status_code == 201
    assert first.json()["chunk_count"] == 1
    assert first.json()["unchanged"] is False
    assert first.json()["status"] == "PARSED"

    repeated = await client.post(
        f"/api/v1/knowledge-bases/{knowledge_base_id}/documents",
        headers=owner_headers,
        files={"file": document},
    )
    assert repeated.status_code == 201
    assert repeated.json()["version_id"] == first.json()["version_id"]
    assert repeated.json()["unchanged"] is True

    isolated = await client.post(
        f"/api/v1/knowledge-bases/{knowledge_base_id}/documents",
        headers=other_headers,
        files={"file": document},
    )
    assert isolated.status_code == 403
    assert isolated.json()["code"] == "ADMIN_REQUIRED"

    indexed = await client.post(
        f"/api/v1/sources/{first.json()['source_id']}/index",
        headers=owner_headers,
    )
    assert indexed.status_code == 200
    assert indexed.json()["indexedChunks"] == 1
    assert indexed.json()["status"] == "READY"


@pytest.mark.asyncio
async def test_failed_upload_does_not_leave_stored_file(client: AsyncClient, tmp_path) -> None:
    token = await admin_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    knowledge_base = await client.post(
        "/api/v1/knowledge-bases", headers=headers, json={"name": "Cleanup"}
    )

    response = await client.post(
        f"/api/v1/knowledge-bases/{knowledge_base.json()['id']}/documents",
        headers=headers,
        files={"file": ("unsafe.env", b"SECRET=value", "text/plain")},
    )

    assert response.status_code == 415
    upload_root = tmp_path / "uploads"
    assert not upload_root.exists() or not any(upload_root.rglob("*.*"))


@pytest.mark.asyncio
async def test_visitor_conversations_and_feedback(client: AsyncClient) -> None:
    owner_token = await admin_token(client)
    owner_headers = {"Authorization": f"Bearer {owner_token}"}
    knowledge_base = await client.post(
        "/api/v1/knowledge-bases",
        headers=owner_headers,
        json={"name": "Public", "is_published": True},
    )
    visitor_headers = {"Authorization": f"Bearer {await visitor_token(client)}"}
    other_headers = {"Authorization": f"Bearer {await visitor_token(client)}"}

    created = await client.post(
        "/api/v1/conversations",
        headers=visitor_headers,
        json={"knowledge_base_id": knowledge_base.json()["id"], "title": "岗位建议"},
    )
    assert created.status_code == 201
    conversation_id = created.json()["id"]

    listed = await client.get("/api/v1/conversations", headers=visitor_headers)
    assert [item["id"] for item in listed.json()] == [conversation_id]

    isolated = await client.get(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=other_headers,
    )
    assert isolated.status_code == 404

    feedback = await client.post(
        "/api/v1/conversations/feedback",
        headers=visitor_headers,
        json={
            "conversation_id": conversation_id,
            "position": "后端工程师",
            "comment": "建议补充分布式项目经验。",
        },
    )
    assert feedback.status_code == 201
    assert feedback.json()["position"] == "后端工程师"

    feedback_list = await client.get("/api/v1/conversations/feedback", headers=owner_headers)
    assert feedback_list.status_code == 200
    assert feedback_list.json()[0]["comment"] == "建议补充分布式项目经验。"

    deleted = await client.delete(
        f"/api/v1/conversations/{conversation_id}", headers=visitor_headers
    )
    assert deleted.status_code == 204
    listed_after_delete = await client.get("/api/v1/conversations", headers=visitor_headers)
    assert listed_after_delete.json() == []
