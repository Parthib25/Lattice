import os
import uuid
import logging
from dotenv import load_dotenv

# Load .env file into os.environ FIRST — before any os.getenv() calls
load_dotenv()

from typing import List, Optional, Dict, Any
from fastapi import Query
from fastapi import FastAPI, Depends, HTTPException, Header, status
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from pydantic import BaseModel, EmailStr
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi import UploadFile, File

from lattice.database.connection import DatabaseConnectionManager
from lattice.database.models import User, Repository, ChatSession, ChatMessage
from lattice.database.repository import UserRepository, RuleRepository, ChatRepository
from lattice.connectors import get_llm_connector, get_search_connector
from lattice.agent import LatticeAgent
import lattice.streaming as streaming_module
from lattice.streaming import router as streaming_router

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("lattice.server")

# Load configuration from environment
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./lattice.db")
DEV_MODE = os.getenv("DEV_MODE", "true").lower() == "true"
WORKSPACE_DIR = os.getenv("WORKSPACE_DIR", ".")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")

# Initialize database manager
db_manager = DatabaseConnectionManager(DATABASE_URL, ssl_verify=False)

app = FastAPI(title="Lattice Feature Feasibility Server", version="0.1.0")

# 1. CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2. Security Headers Middleware
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

app.add_middleware(SecurityHeadersMiddleware)

# 3. Database Exception Shielding
@app.exception_handler(IntegrityError)
async def integrity_exception_handler(request: Request, exc: IntegrityError):
    logger.error(f"Database Integrity conflict: {exc}")
    return Response(
        content='{"detail": "Resource conflict. Unique constraint or foreign key violation."}',
        status_code=status.HTTP_409_CONFLICT,
        media_type="application/json"
    )

@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError):
    logger.error(f"Database error: {exc}")
    return Response(
        content='{"detail": "A database error occurred. Internal details have been shielded."}',
        status_code=status.HTTP_400_BAD_REQUEST,
        media_type="application/json"
    )

# 4. Async Session Dependency
async def get_db_session():
    async with db_manager.get_session() as session:
        yield session

# 5. User Auth & Role Check Dependency
async def get_current_user(
    x_user_email: Optional[str] = Header(None, alias="X-User-Email"),
    authorization: Optional[str] = Header(None),
    token: Optional[str] = Query(None),  # SSE fallback: EventSource can't send headers
    session: AsyncSession = Depends(get_db_session)
) -> User:
    email = None
    
    if DEV_MODE and x_user_email:
        email = x_user_email
    else:
        # Resolve the raw JWT: prefer Authorization header, fallback to ?token= query param (SSE)
        raw_token = None
        if authorization and authorization.startswith("Bearer "):
            raw_token = authorization.split(" ")[1]
        elif token:
            raw_token = token

        if raw_token:
            try:
                import base64, json as _json
                parts = raw_token.split('.')
                if len(parts) == 3:
                    padded = parts[1] + '=' * (4 - len(parts[1]) % 4)
                    payload = _json.loads(base64.urlsafe_b64decode(padded))
                    email = payload.get('email')
                    if not email:
                        logger.warning("Google JWT decoded but no 'email' claim found.")
            except Exception as jwt_err:
                logger.warning(f"Failed to decode JWT payload: {jwt_err}")
            
    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials missing or invalid."
        )
        
    user = await UserRepository.get_by_email(session, email)
    if not user:
        logger.info(f"User '{email}' not found. Auto-registering with USER role...")
        username = email.split('@')[0]
        user = await UserRepository.create(
            session=session,
            username=username,
            email=email,
            role="USER"
        )
        await session.commit()
    return user

def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "ADMIN":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="ADMIN privileges required to execute this operation."
        )
    return user

# Pydantic Schemas for Requests
class RepositoryCreate(BaseModel):
    name: str
    vcs_url: str
    custom_domain: Optional[str] = None

class ChatSessionCreate(BaseModel):
    title: str
    repo_id: uuid.UUID
    provider: str
    model: Optional[str] = None
    rules_markdown: Optional[str] = None

# ─── Mount Streaming Router ─────────────────────────────────────────────────
app.dependency_overrides[streaming_module._placeholder_get_session] = get_db_session
app.dependency_overrides[streaming_module._placeholder_get_current_user] = get_current_user

app.include_router(streaming_router)

# Mount static files directory
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def get_dashboard():
    return FileResponse("static/index.html")

@app.get("/api/config")
async def get_public_config():
    return {
        "google_client_id": GOOGLE_CLIENT_ID,
        "dev_mode": DEV_MODE
    }

@app.on_event("startup")
async def initialize_database_schema():
    """Automatically creates schema tables in the target database if they do not exist."""
    from lattice.database.models import Base, User, Repository
    from sqlalchemy import text
    try:
        # 1. Ensure all schema tables exist
        async with db_manager.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            
        # 2. Add active_role to users table (independent transaction)
        try:
            async with db_manager.engine.begin() as conn:
                await conn.execute(text("ALTER TABLE users ADD COLUMN active_role VARCHAR(50) DEFAULT 'USER' NOT NULL"))
                logger.info("Migrated users table: added 'active_role' column.")
        except Exception:
            pass

        # 3. Increase role column width to 200 (independent transaction)
        try:
            async with db_manager.engine.begin() as conn:
                await conn.execute(text("ALTER TABLE users ALTER COLUMN role TYPE VARCHAR(200)"))
                logger.info("Migrated users table: increased 'role' column type width.")
        except Exception:
            pass

        # 4. Add rules_markdown to chat_sessions (independent transaction)
        try:
            async with db_manager.engine.begin() as conn:
                await conn.execute(text("ALTER TABLE chat_sessions ADD COLUMN rules_markdown TEXT"))
                logger.info("Migrated chat_sessions table: added 'rules_markdown' column.")
        except Exception:
            pass

        logger.info("Database schema initialized/verified successfully.")

        if DEV_MODE:
            async with db_manager.get_session() as session:
                from sqlalchemy import select
                user_check = await session.execute(select(User).where(User.email == "sse@example.com"))
                if not user_check.scalar_one_or_none():
                    logger.info("DEV_MODE active: Seeding default user 'sse@example.com'...")
                    dev_user = User(
                        id=uuid.uuid4(),
                        username="developer",
                        email="sse@example.com",
                        role="USER"
                    )
                    session.add(dev_user)
                    
                    repo_check = await session.execute(select(Repository))
                    if not repo_check.scalars().first():
                        logger.info("Seeding default repository 'lattice-test-repo'...")
                        default_repo = Repository(
                            id=uuid.uuid4(),
                            name="lattice-test-repo",
                            vcs_url="https://github.com/org/repo"
                        )
                        session.add(default_repo)
                    await session.commit()
    except Exception as e:
        logger.error(f"Failed to auto-initialize or seed database on startup: {e}")

# ─── Template Import/Export endpoints ───────────────────────────────────────
@app.get("/api/rules/template")
async def get_rules_template(user: User = Depends(get_current_user)):
    template_path = os.path.join(WORKSPACE_DIR, "static", "rules.md")
    if not os.path.exists(template_path):
        from lattice.rules_parser import DEFAULT_TEMPLATE
        with open(template_path, "w", encoding="utf-8") as f:
            f.write(DEFAULT_TEMPLATE)
    return FileResponse(template_path, media_type="text/markdown", filename="rules.md")

@app.post("/api/rules/upload")
async def upload_rules_file(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user)
):
    from lattice.rules_parser import parse_rules_markdown
    contents = await file.read()
    text = contents.decode("utf-8")
    try:
        parsed = parse_rules_markdown(text)
        if not parsed:
            raise ValueError("No valid Component blocks found. Check formatting.")
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid rules markdown format: {e}"
        )
    template_path = os.path.join(WORKSPACE_DIR, "static", "rules.md")
    with open(template_path, "w", encoding="utf-8") as f:
        f.write(text)
    return {"message": "Rules updated successfully", "rules_parsed_count": len(parsed)}

# ─── REST Repositories Endpoints ────────────────────────────────────────────
@app.get("/api/repositories")
async def list_repositories(session: AsyncSession = Depends(get_db_session), user: User = Depends(get_current_user)):
    repos = await RuleRepository.list_repositories(session)
    return [{"id": str(r.id), "name": r.name, "vcs_url": r.vcs_url, "custom_domain": r.custom_domain} for r in repos]

@app.post("/api/repositories", status_code=status.HTTP_201_CREATED)
async def create_repository(
    data: RepositoryCreate, 
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user)
):
    if user.active_role != "ADMIN":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="ADMIN privileges required to execute this operation."
        )
    repo = await RuleRepository.create_repository(session, data.name, data.vcs_url, data.custom_domain)
    await session.commit() # commit changes to db
    return {"id": str(repo.id), "name": repo.name}


# ─── Chat History Endpoints ──────────────────────────────────────────────────
@app.get("/api/chats")
async def list_chats(session: AsyncSession = Depends(get_db_session), user: User = Depends(get_current_user)):
    sessions = await ChatRepository.list_sessions(session, user.id)
    return [
        {
            "id": str(s.id),
            "title": s.title,
            "repo_id": str(s.repo_id),
            "repo_name": s.repository.name if s.repository else "",
            "provider": s.provider,
            "model": s.model,
            "created_at": s.created_at.isoformat()
        } for s in sessions
    ]

@app.post("/api/chats", status_code=status.HTTP_201_CREATED)
async def create_chat(data: ChatSessionCreate, session: AsyncSession = Depends(get_db_session), user: User = Depends(get_current_user)):
    rules_text = data.rules_markdown
    if not rules_text:
        rules_path = os.path.join(WORKSPACE_DIR, "static", "rules.md")
        if os.path.exists(rules_path):
            with open(rules_path, "r", encoding="utf-8") as f:
                rules_text = f.read()
                
    sess = await ChatRepository.create_session(
        session, user.id, data.title, data.repo_id, data.provider, data.model, rules_markdown=rules_text
    )
    await session.commit()
    return {
        "id": str(sess.id),
        "title": sess.title,
        "repo_id": str(sess.repo_id),
        "provider": sess.provider,
        "model": sess.model
    }

@app.get("/api/chats/{session_id}")
async def get_chat_details(session_id: uuid.UUID, session: AsyncSession = Depends(get_db_session), user: User = Depends(get_current_user)):
    sess = await ChatRepository.get_session(session, session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="Chat session not found.")
    if sess.user_id != user.id:
        raise HTTPException(status_code=403, detail="Access denied.")
    return {
        "id": str(sess.id),
        "title": sess.title,
        "repo_id": str(sess.repo_id),
        "provider": sess.provider,
        "model": sess.model,
        "messages": [
            {
                "id": str(m.id),
                "role": m.role,
                "content": m.content,
                "live_logs": m.live_logs,
                "created_at": m.created_at.isoformat()
            } for m in sess.messages
        ]
    }

@app.delete("/api/chats/{session_id}")
async def delete_chat(session_id: uuid.UUID, session: AsyncSession = Depends(get_db_session), user: User = Depends(get_current_user)):
    sess = await ChatRepository.get_session(session, session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="Chat session not found.")
    if sess.user_id != user.id:
        raise HTTPException(status_code=403, detail="Access denied.")
    await ChatRepository.delete_session(session, session_id)
    await session.commit()
    return {"message": "Chat session deleted successfully."}

@app.get("/api/users/me")
async def get_me(user: User = Depends(get_current_user)):
    return {
        "id": str(user.id),
        "username": user.username,
        "email": user.email,
        "roles": [r.strip() for r in user.role.split(",") if r.strip()],
        "active_role": user.active_role
    }

class RoleUpdate(BaseModel):
    role: str

@app.post("/api/users/role")
async def update_my_role(
    data: RoleUpdate,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user)
):
    assigned_roles = [r.strip() for r in user.role.split(",") if r.strip()]
    if data.role not in assigned_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied. You do not possess the '{data.role}' role."
        )
    user.active_role = data.role
    await session.commit()
    return {"message": f"Successfully switched session to {data.role} active role."}
