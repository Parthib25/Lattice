import asyncio
import uuid
import pytest
import pytest_asyncio
from hypothesis import given, strategies as st, settings
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from lattice.database.models import Base
from lattice.database.connection import DatabaseConnectionManager
from lattice.database.repository import UserRepository, RuleRepository, ChatRepository

# Database connection URL for testing (SQLite in-memory)
TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest_asyncio.fixture(scope="function")
async def db_manager():
    manager = DatabaseConnectionManager(TEST_DB_URL, ssl_verify=False)
    async with manager.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield manager
    await manager.close()

@pytest.mark.asyncio
async def test_create_user(db_manager):
    async with db_manager.get_session() as session:
        user = await UserRepository.create(session, "regular_user", "user@example.com", "USER")
        assert user.username == "regular_user"
        assert user.email == "user@example.com"
        assert user.role == "USER"

        # Retrieve user
        fetched = await UserRepository.get_by_email(session, "user@example.com")
        assert fetched is not None
        assert fetched.username == "regular_user"

@pytest.mark.asyncio
async def test_chat_session_flow(db_manager):
    async with db_manager.get_session() as session:
        # Create dependencies
        user = await UserRepository.create(session, "alice", "alice@example.com", "USER")
        repo = await RuleRepository.create_repository(session, "app-repo", "https://github.com/a/b")
        
        # Create session
        chat_sess = await ChatRepository.create_session(
            session=session,
            user_id=user.id,
            title="Feasibility Check 1",
            repo_id=repo.id,
            provider="openai",
            model="gpt-4o"
        )
        assert chat_sess.title == "Feasibility Check 1"
        assert chat_sess.repo_id == repo.id
        
        # Add messages
        m1 = await ChatRepository.add_message(session, chat_sess.id, "user", "Add oauth2 login")
        m2 = await ChatRepository.add_message(session, chat_sess.id, "assistant", "Report content...", "Live log output here")
        
        await session.commit()
        
    async with db_manager.get_session() as session:
        # Get session details
        fetched_sess = await ChatRepository.get_session(session, chat_sess.id)
        assert fetched_sess is not None
        assert fetched_sess.title == "Feasibility Check 1"
        assert len(fetched_sess.messages) == 2
        assert fetched_sess.messages[0].role == "user"
        assert fetched_sess.messages[1].role == "assistant"
        assert fetched_sess.messages[1].live_logs == "Live log output here"

# Hypothesis strategies for properties
email_strategy = st.from_regex(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$", fullmatch=True)
username_strategy = st.text(min_size=2, max_size=50, alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd')))

@pytest.mark.asyncio
@given(
    username=username_strategy,
    email=email_strategy,
    role=st.sampled_from(["ADMIN", "LEAD", "USER"])
)
@settings(max_examples=10, deadline=None)
async def test_pbt_user_roundtrip(username, email, role):
    """PBT verification for User record creation and querying (PBT-02/PBT-03)."""
    manager = DatabaseConnectionManager(TEST_DB_URL, ssl_verify=False)
    async with manager.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with manager.get_session() as session:
        user = await UserRepository.create(session, username, email, role)
        assert user.username == username
        assert user.email == email
        assert user.role == role

        fetched = await UserRepository.get_by_email(session, email)
        assert fetched is not None
        assert fetched.id == user.id
        assert fetched.username == username
        assert fetched.email == email
        assert fetched.role == role

    await manager.close()
