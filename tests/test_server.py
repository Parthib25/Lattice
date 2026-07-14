import os
import uuid
import pytest
import pytest_asyncio
import httpx
from sqlalchemy.ext.asyncio import create_async_engine
from lattice.database.models import Base
from lattice.database.connection import DatabaseConnectionManager
from lattice.database.repository import UserRepository, RuleRepository
from lattice.server import app, db_manager

# Ensure dev mode is enabled during test run
os.environ["DEV_MODE"] = "true"
TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

@pytest_asyncio.fixture(scope="function", autouse=True)
async def setup_test_db():
    db_manager.db_url = TEST_DB_URL
    db_manager._init_engine()
    
    async with db_manager.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
    async with db_manager.get_session() as session:
        await UserRepository.create(session, "admin_user", "admin@example.com", "ADMIN")
        await UserRepository.create(session, "regular_user", "user@example.com", "USER")
        
    yield
    await db_manager.close()


@pytest.mark.asyncio
async def test_auth_missing_header():
    """Accessing endpoints without credentials returns HTTP 401."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/api/users/me")
        assert response.status_code == 401
        assert "Authentication credentials missing" in response.json()["detail"]


@pytest.mark.asyncio
async def test_auth_auto_registers_user():
    """Accessing with an unregistered email automatically registers the user with USER role."""
    headers = {"X-User-Email": "new_stranger@example.com"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/api/users/me", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "new_stranger@example.com"
        assert data["role"] == "USER"


@pytest.mark.asyncio
async def test_get_me_profile():
    """Retrieving personal user details via X-User-Email header."""
    headers = {"X-User-Email": "user@example.com"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/api/users/me", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "regular_user"
        assert data["role"] == "USER"


@pytest.mark.asyncio
async def test_role_based_crud_controls():
    """Standard USER roles cannot execute admin operations."""
    headers_user = {"X-User-Email": "user@example.com"}
    headers_admin = {"X-User-Email": "admin@example.com"}
    
    payload = {"name": "Product Repo", "vcs_url": "https://github.com/org/repo"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        # USER tries to create repository -> HTTP 403 Forbidden
        res = await client.post("/api/repositories", json=payload, headers=headers_user)
        assert res.status_code == 403
        
        # ADMIN creates repository -> HTTP 201 Created
        res_admin = await client.post("/api/repositories", json=payload, headers=headers_admin)
        assert res_admin.status_code == 201
        assert res_admin.json()["name"] == "Product Repo"
