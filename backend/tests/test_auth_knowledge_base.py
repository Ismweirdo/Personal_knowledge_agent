from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.infrastructure.database import get_session
from app.infrastructure.models import Base
from app.main import create_app


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = override_session
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


@pytest.mark.asyncio
async def test_register_login_and_duplicate_email(client: AsyncClient) -> None:
    token = await register(client, "user@example.com")
    assert token

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "USER@example.com", "password": "secure-password"},
    )
    assert login.status_code == 200

    duplicate = await client.post(
        "/api/v1/auth/register",
        json={"email": "user@example.com", "password": "secure-password"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "EMAIL_ALREADY_EXISTS"


@pytest.mark.asyncio
async def test_knowledge_bases_require_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/knowledge-bases")
    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_REQUIRED"


@pytest.mark.asyncio
async def test_knowledge_base_crud_and_user_isolation(client: AsyncClient) -> None:
    first_token = await register(client, "first@example.com")
    second_token = await register(client, "second@example.com")
    first_headers = {"Authorization": f"Bearer {first_token}"}
    second_headers = {"Authorization": f"Bearer {second_token}"}

    created = await client.post(
        "/api/v1/knowledge-bases",
        headers=first_headers,
        json={"name": "Notes", "description": "Personal notes"},
    )
    assert created.status_code == 201
    knowledge_base_id = created.json()["id"]

    listed = await client.get("/api/v1/knowledge-bases", headers=first_headers)
    assert [item["id"] for item in listed.json()] == [knowledge_base_id]

    forbidden_as_not_found = await client.patch(
        f"/api/v1/knowledge-bases/{knowledge_base_id}",
        headers=second_headers,
        json={"name": "Stolen"},
    )
    assert forbidden_as_not_found.status_code == 404

    deleted = await client.delete(
        f"/api/v1/knowledge-bases/{knowledge_base_id}", headers=first_headers
    )
    assert deleted.status_code == 204
