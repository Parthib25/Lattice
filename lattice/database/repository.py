import uuid
from typing import List, Optional
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from lattice.database.models import User, Repository, ChatSession, ChatMessage

class UserRepository:
    @staticmethod
    async def get_by_email(session: AsyncSession, email: str) -> Optional[User]:
        stmt = select(User).where(User.email == email)
        result = await session.execute(stmt)
        return result.scalars().first()

    @staticmethod
    async def get_by_id(session: AsyncSession, user_id: uuid.UUID) -> Optional[User]:
        stmt = select(User).where(User.id == user_id)
        result = await session.execute(stmt)
        return result.scalars().first()

    @staticmethod
    async def list_all(session: AsyncSession) -> List[User]:
        stmt = select(User)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def create(
        session: AsyncSession,
        username: str,
        email: str,
        role: str = "USER"
    ) -> User:
        user = User(
            username=username,
            email=email,
            role=role,
            active_role=role.split(",")[0] if "," in role else role
        )
        session.add(user)
        await session.flush()
        return user

    @staticmethod
    async def update_role(session: AsyncSession, user_id: uuid.UUID, role: str) -> Optional[User]:

        user = await UserRepository.get_by_id(session, user_id)
        if user:
            user.role = role
            await session.flush()
        return user


class RuleRepository:
    @staticmethod
    async def get_repository_by_id(session: AsyncSession, repo_id: uuid.UUID) -> Optional[Repository]:
        stmt = select(Repository).where(Repository.id == repo_id)
        result = await session.execute(stmt)
        return result.scalars().first()

    @staticmethod
    async def list_repositories(session: AsyncSession) -> List[Repository]:
        stmt = select(Repository)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def create_repository(
        session: AsyncSession,
        name: str,
        vcs_url: str,
        custom_domain: Optional[str] = None
    ) -> Repository:
        repo = Repository(name=name, vcs_url=vcs_url, custom_domain=custom_domain)
        session.add(repo)
        await session.flush()
        return repo


class ChatRepository:
    @staticmethod
    async def create_session(
        session: AsyncSession,
        user_id: uuid.UUID,
        title: str,
        repo_id: uuid.UUID,
        provider: str,
        model: Optional[str] = None,
        rules_markdown: Optional[str] = None
    ) -> ChatSession:
        chat_sess = ChatSession(
            user_id=user_id,
            repo_id=repo_id,
            title=title,
            provider=provider,
            model=model,
            rules_markdown=rules_markdown
        )
        session.add(chat_sess)
        await session.flush()
        return chat_sess

    @staticmethod
    async def list_sessions(session: AsyncSession, user_id: uuid.UUID) -> List[ChatSession]:
        stmt = (
            select(ChatSession)
            .where(ChatSession.user_id == user_id)
            .order_by(ChatSession.created_at.desc())
            .options(selectinload(ChatSession.repository))
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_session(session: AsyncSession, session_id: uuid.UUID) -> Optional[ChatSession]:
        stmt = (
            select(ChatSession)
            .where(ChatSession.id == session_id)
            .options(
                selectinload(ChatSession.repository),
                selectinload(ChatSession.messages)
            )
        )
        result = await session.execute(stmt)
        return result.scalars().first()

    @staticmethod
    async def delete_session(session: AsyncSession, session_id: uuid.UUID) -> bool:
        stmt = select(ChatSession).where(ChatSession.id == session_id)
        result = await session.execute(stmt)
        chat_sess = result.scalars().first()
        if chat_sess:
            await session.delete(chat_sess)
            await session.flush()
            return True
        return False

    @staticmethod
    async def add_message(
        session: AsyncSession,
        session_id: uuid.UUID,
        role: str,
        content: str,
        live_logs: Optional[str] = None
    ) -> ChatMessage:
        msg = ChatMessage(
            session_id=session_id,
            role=role,
            content=content,
            live_logs=live_logs
        )
        session.add(msg)
        await session.flush()
        return msg

    @staticmethod
    async def get_messages(session: AsyncSession, session_id: uuid.UUID) -> List[ChatMessage]:
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.ascii())
            if hasattr(ChatMessage.created_at, "ascii") else
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.asc())
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

