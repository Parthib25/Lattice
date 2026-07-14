"""
lattice/streaming.py

Two-phase SSE streaming endpoint with DB persistence for chat history.
"""
import asyncio
import json
import logging
import uuid
import os
from dotenv import load_dotenv
from typing import Dict, Any, Optional, AsyncGenerator, List

load_dotenv()

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

logger = logging.getLogger("lattice.streaming")

# ─── Constants ───────────────────────────────────────────────────────────────
MAX_CONCURRENT_RUNS: int = 100
QUEUE_MAXSIZE: int = 100
RUN_TTL_SECONDS: int = 120
HEARTBEAT_INTERVAL: float = 15.0
WORKSPACE_DIR: str = os.getenv("WORKSPACE_DIR", ".")

# ─── In-Memory Run Registry ──────────────────────────────────────────────────
# Structure: { run_id: { "queue": asyncio.Queue, "user_id": str } }
run_registry: Dict[str, Dict[str, Any]] = {}

# ─── Router ──────────────────────────────────────────────────────────────────
router = APIRouter(prefix="/api/feasibility", tags=["Streaming"])

# ─── Placeholder Dependency Sentinels ────────────────────────────────────────
async def _placeholder_get_session():
    raise NotImplementedError("DB session dependency not wired.")
    yield

async def _placeholder_get_current_user():
    raise NotImplementedError("User auth dependency not wired.")

# ─── Request Schema ───────────────────────────────────────────────────────────
class StreamRequest(BaseModel):
    session_id: Optional[uuid.UUID] = None
    repo_id: uuid.UUID
    feature_request: str
    provider: str = "openai"
    model: Optional[str] = None

# ─── Background Cleanup Task ──────────────────────────────────────────────────
async def cleanup_run(run_id: str, delay: int = RUN_TTL_SECONDS) -> None:
    await asyncio.sleep(delay)
    run_registry.pop(run_id, None)
    logger.info(f"Cleaned up SSE run: {run_id}")

# ─── Background Agent Task ────────────────────────────────────────────────────
async def run_agent_task(
    run_id: str,
    session_id: uuid.UUID,
    feature_request: str,
    rules: list,
    provider: str,
    model: Optional[str],
    custom_domain: Optional[str],
    db_session_factory, # callable returning get_session context
    repo_name: str = "repository",
    vcs_url: str = "",
) -> None:
    from lattice.connectors import get_llm_connector, get_search_connector
    from lattice.agent import LatticeAgent
    from lattice.database.repository import ChatRepository

    queue: asyncio.Queue = run_registry[run_id]["queue"]
    log_buffer: List[str] = []

    def log_callback(event: Dict[str, Any]) -> None:
        # Build human-readable live logs to store in DB
        msg = event.get("message", "")
        node = event.get("node", "")
        ev = event.get("event", "")
        if ev == "node_start":
            log_line = f"[{node.upper()} START] {msg}"
        elif ev == "node_complete":
            log_line = f"[{node.upper()} COMPLETE] {msg}"
        else:
            log_line = msg
        if log_line:
            log_buffer.append(log_line)
        asyncio.create_task(queue.put(event))

    final_report = ""
    error_occurred = False
    error_msg = ""
    
    # Fetch chat history
    chat_history = []
    try:
        async with db_session_factory() as session:
            existing_messages = await ChatRepository.get_messages(session, session_id)
            for m in existing_messages:
                chat_history.append({"role": m.role, "content": m.content})
    except Exception as e:
        logger.error(f"Failed to fetch chat history: {e}")
        
    chat_history.append({"role": "user", "content": feature_request})

    try:
        prov_upper = provider.upper()
        api_key = os.getenv(f"{prov_upper}_API_KEY") or os.getenv("API_KEY", "mock-key")
        llm = get_llm_connector(provider, api_key=api_key, model=model)

        sg_url = custom_domain or os.getenv("SOURCEGRAPH_URL")
        sg_token = os.getenv("SRC_ACCESS_TOKEN", "mock-token")

        if sg_url:
            searcher = get_search_connector(
                "sourcegraph",
                base_path=WORKSPACE_DIR,
                token=sg_token,
                endpoint_url=sg_url,
            )
        elif vcs_url.startswith("https://github.com/"):
            gh_token = os.getenv("GITHUB_TOKEN", "")
            searcher = get_search_connector(
                "github",
                base_path=WORKSPACE_DIR,
                token=gh_token,
            )
        else:
            searcher = get_search_connector("local", base_path=WORKSPACE_DIR)

        agent = LatticeAgent(llm, searcher, log_callback=log_callback)
        result = await agent.run(feature_request, rules=rules, chat_history=chat_history, repo_name=repo_name, vcs_url=vcs_url)
        
        is_clear = result.get("is_clear", True)
        if not is_clear:
            final_report = result.get("clarifying_question", "Could you provide more details?")
        else:
            final_report = result.get("final_report", "")
            
        matching_rules_list = result.get("matching_rules", [])

    except Exception as exc:
        logger.error(f"Agent run {run_id} failed: {exc}")
        error_occurred = True
        error_msg = str(exc)
        matching_rules_list = []
        await queue.put({"event": "error", "message": error_msg})

    # Persist results directly to DB session
    try:
        async with db_session_factory() as session:
            # 1. Save User prompt if not already present
            existing_messages = await ChatRepository.get_messages(session, session_id)
            if not existing_messages or existing_messages[-1].role != 'user':
                await ChatRepository.add_message(
                    session=session,
                    session_id=session_id,
                    role='user',
                    content=feature_request
                )

            # 2. Save Assistant response
            content_to_save = final_report if not error_occurred else f"⚠️ Error: {error_msg}"
            logs_to_save = "\n".join(log_buffer)
            await ChatRepository.add_message(
                session=session,
                session_id=session_id,
                role='assistant',
                content=content_to_save,
                live_logs=logs_to_save
            )
            await session.commit()
            logger.info(f"Saved messages for session {session_id} to DB successfully.")
    except Exception as db_err:
        logger.error(f"Failed to auto-save streaming run to database: {db_err}")

    await queue.put(
        {
            "event": "done",
            "final_report": final_report,
            "matching_rules": matching_rules_list,
        }
    )
    asyncio.create_task(cleanup_run(run_id))


# ─── SSE Event Generator ──────────────────────────────────────────────────────
async def _event_generator(run_id: str) -> AsyncGenerator[Dict[str, Any], None]:
    queue: asyncio.Queue = run_registry[run_id]["queue"]
    while True:
        try:
            event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_INTERVAL)
            yield {"data": json.dumps(event)}
            if event.get("event") == "done":
                asyncio.create_task(cleanup_run(run_id))
                break
        except asyncio.TimeoutError:
            yield {"comment": "heartbeat"}


# ─── Phase 1: Trigger ─────────────────────────────────────────────────────────
@router.post("/stream", status_code=status.HTTP_202_ACCEPTED)
async def trigger_stream(
    data: StreamRequest,
    session: AsyncSession = Depends(_placeholder_get_session),
    user: Any = Depends(_placeholder_get_current_user),
):
    from lattice.database.repository import RuleRepository, ChatRepository
    from lattice.rules_parser import parse_rules_markdown

    if len(run_registry) >= MAX_CONCURRENT_RUNS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many concurrent evaluation runs. Please retry later.",
            headers={"Retry-After": "30"},
        )

    # Validate repo exists
    repo = await RuleRepository.get_repository_by_id(session, data.repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found in database.")

    # Resolve session_id and rules_markdown
    session_id = data.session_id
    rules_text = ""
    
    if session_id:
        # Load rules from the existing chat session record
        sess = await ChatRepository.get_session(session, session_id)
        if not sess:
            raise HTTPException(status_code=404, detail="Chat session not found.")
        if sess.user_id != user.id:
            raise HTTPException(status_code=403, detail="Access denied.")
            
        # Update session with the latest selected parameters on rerun
        sess.provider = data.provider
        sess.model = data.model
        sess.repo_id = data.repo_id
        
        rules_text = sess.rules_markdown
        if not rules_text:
            # Fallback to static rules.md for legacy sessions and update session rules
            rules_file_path = os.path.join(WORKSPACE_DIR, "static", "rules.md")
            if os.path.exists(rules_file_path):
                with open(rules_file_path, "r", encoding="utf-8") as f:
                    rules_text = f.read()
                    sess.rules_markdown = rules_text
        await session.commit()
    else:
        # Read current global rules.md for new session
        rules_file_path = os.path.join(WORKSPACE_DIR, "static", "rules.md")
        if os.path.exists(rules_file_path):
            with open(rules_file_path, "r", encoding="utf-8") as f:
                rules_text = f.read()
                
        title = data.feature_request[:40].strip() or "New Feasibility Check"
        if len(data.feature_request) > 40:
            title += "..."
        new_sess = await ChatRepository.create_session(
            session=session,
            user_id=user.id,
            title=title,
            repo_id=data.repo_id,
            provider=data.provider,
            model=data.model,
            rules_markdown=rules_text
        )
        await session.commit()
        session_id = new_sess.id

    # Parse loaded rules
    rules_list = []
    if rules_text:
        try:
            rules_list = parse_rules_markdown(rules_text)
        except Exception as e:
            logger.error(f"Failed to parse session rules: {e}")

    # Register new run
    run_id = str(uuid.uuid4())
    run_registry[run_id] = {
        "queue": asyncio.Queue(maxsize=QUEUE_MAXSIZE),
        "user_id": str(user.id),
    }

    # Pass DB manager session context factory directly to background task
    from lattice.server import db_manager
    db_session_factory = db_manager.get_session

    asyncio.create_task(
        run_agent_task(
            run_id=run_id,
            session_id=session_id,
            feature_request=data.feature_request,
            rules=rules_list,
            provider=data.provider,
            model=data.model,
            custom_domain=repo.custom_domain,
            db_session_factory=db_session_factory,
            repo_name=repo.name,
            vcs_url=repo.vcs_url,
        )
    )

    return {"run_id": run_id, "session_id": str(session_id)}


# ─── Phase 2: Subscribe ───────────────────────────────────────────────────────
@router.get("/stream/{run_id}")
async def subscribe_stream(
    run_id: str,
    user: Any = Depends(_placeholder_get_current_user),
):
    if run_id not in run_registry:
        raise HTTPException(
            status_code=404,
            detail=f"Run '{run_id}' not found or has expired.",
        )

    entry = run_registry[run_id]
    if entry["user_id"] != str(user.id):
        raise HTTPException(status_code=403, detail="Access denied to this run.")

    return EventSourceResponse(_event_generator(run_id))
