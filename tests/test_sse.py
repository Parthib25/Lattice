import asyncio
import json
import uuid
from typing import List, Dict, Any
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from lattice.server import app, get_db_session, get_current_user
from lattice.database.models import Base, User, Repository
from lattice.streaming import run_registry, MAX_CONCURRENT_RUNS

# ─── Test Database Setup ─────────────────────────────────────────────────────
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"
test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestingSessionLocal = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture(autouse=True)
async def setup_database():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    run_registry.clear()


@pytest_asyncio.fixture
async def db_session():
    async with TestingSessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def seeded_user_and_repo(db_session: AsyncSession):
    """Seeds a test user and repository, returns (user, repo)."""
    user = User(
        username="sse_tester",
        email="sse@example.com",
        role="USER"
    )
    db_session.add(user)
    await db_session.flush()

    repo = Repository(name="sse-repo", vcs_url="https://github.com/org/sse-repo")
    db_session.add(repo)
    await db_session.commit()
    await db_session.refresh(user)
    await db_session.refresh(repo)
    return user, repo


@pytest_asyncio.fixture
async def client(seeded_user_and_repo):
    """Async HTTP client with dependency overrides for auth and session."""
    seeded_user, seeded_repo = seeded_user_and_repo

    async def override_get_db_session():
        async with TestingSessionLocal() as s:
            yield s

    async def override_get_current_user():
        async with TestingSessionLocal() as s:
            from sqlalchemy import select
            from lattice.database.models import User
            result = await s.execute(select(User).where(User.email == "sse@example.com"))
            return result.scalar_one()

    # Override placeholders
    from lattice.streaming import _placeholder_get_session, _placeholder_get_current_user
    app.dependency_overrides[_placeholder_get_session] = override_get_db_session
    app.dependency_overrides[_placeholder_get_current_user] = override_get_current_user

    # Also override base dependencies in case server needs them directly
    app.dependency_overrides[get_db_session] = override_get_db_session
    app.dependency_overrides[get_current_user] = override_get_current_user

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c, seeded_repo

    app.dependency_overrides.clear()


# ─── SSE Event Collection Helper ─────────────────────────────────────────────
async def collect_sse_events(client: AsyncClient, url: str) -> List[Dict[str, Any]]:
    """Reads all SSE data events from a streaming response until the stream closes."""
    events = []
    async with client.stream("GET", url) as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
        async for line in response.aiter_lines():
            if line.startswith("data:"):
                event_data = line[5:].strip()
                events.append(json.loads(event_data))
    return events


# ─── Scenario 1: Full Stream Lifecycle (Happy Path) ──────────────────────────
@pytest.mark.asyncio
async def test_full_stream_lifecycle(client):
    http_client, seeded_repo = client

    # Phase 1: Trigger to register a run_id
    trigger_resp = await http_client.post(
        "/api/feasibility/stream",
        json={
            "repo_id": str(seeded_repo.id),
            "feature_request": "Add OAuth login button"
        }
    )
    assert trigger_resp.status_code == 202
    body = trigger_resp.json()
    assert "run_id" in body
    run_id = body["run_id"]
    assert run_id in run_registry

    # Directly push events into the run queue to simulate agent execution
    queue = run_registry[run_id]["queue"]
    await queue.put({"event": "node_start", "node": "parse", "message": "Parsing request..."})
    await queue.put({"event": "node_complete", "node": "parse", "message": "Parsing done."})
    await queue.put({"event": "node_start", "node": "search", "message": "Searching code..."})
    await queue.put({"event": "node_complete", "node": "search", "message": "Search done."})
    await queue.put({
        "event": "done",
        "final_report": "# Feasibility Analysis\nFeature is feasible.",
        "matching_rules": []
    })

    # Phase 2: Subscribe and collect all emitted SSE events
    events = await collect_sse_events(http_client, f"/api/feasibility/stream/{run_id}")

    assert len(events) >= 5, f"Expected at least 5 events, got: {len(events)}"

    event_types = [e.get("event") for e in events]
    assert "node_start" in event_types
    assert "node_complete" in event_types
    assert events[-1]["event"] == "done"
    assert len(events[-1]["final_report"]) > 0


# ─── Scenario 2: Invalid Run ID ───────────────────────────────────────────────
@pytest.mark.asyncio
async def test_subscribe_invalid_run_id(client):
    http_client, _ = client

    response = await http_client.get("/api/feasibility/stream/nonexistent-run-id-00000")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


# ─── Scenario 3: Concurrent Run Limit ────────────────────────────────────────
@pytest.mark.asyncio
async def test_concurrent_run_limit(client):
    http_client, seeded_repo = client

    # Artificially fill the registry to the limit
    for i in range(MAX_CONCURRENT_RUNS):
        run_registry[str(uuid.uuid4())] = {
            "queue": asyncio.Queue(maxsize=100),
            "user_id": "any-user"
        }

    trigger_resp = await http_client.post(
        "/api/feasibility/stream",
        json={
            "repo_id": str(seeded_repo.id),
            "feature_request": "Too many runs already in progress"
        }
    )

    assert trigger_resp.status_code == 429
    assert "Retry-After" in trigger_resp.headers
    assert trigger_resp.headers["Retry-After"] == "30"


# ─── Scenario 4: Phase 2 Access Denied for Wrong User ────────────────────────
@pytest.mark.asyncio
async def test_subscribe_access_denied_wrong_user(client):
    http_client, seeded_repo = client

    # Insert a run that belongs to a different user
    other_run_id = str(uuid.uuid4())
    run_registry[other_run_id] = {
        "queue": asyncio.Queue(maxsize=100),
        "user_id": str(uuid.uuid4())   # A different user's ID
    }

    response = await http_client.get(f"/api/feasibility/stream/{other_run_id}")
    assert response.status_code == 403
    assert "Access denied" in response.json()["detail"]
