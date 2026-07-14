import asyncio
import logging
import random
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

logger = logging.getLogger("lattice.database.connection")

class DatabaseConnectionError(Exception):
    """Raised when the database connection cannot be established after retries."""
    pass

class DatabaseConnectionManager:
    def __init__(self, db_url: str, ssl_verify: bool = True):
        self.db_url = db_url
        self.ssl_verify = ssl_verify
        self.engine = None
        self.session_factory = None
        self._init_engine()

    def _init_engine(self):
        import os
        schema = os.getenv("DB_SCHEMA")
        connect_args = {}
        
        # Parse driver and configure SSL / Schema settings if needed
        if "postgresql+asyncpg" in self.db_url:
            if self.ssl_verify:
                connect_args["ssl"] = "require"
            if schema:
                connect_args["server_settings"] = {"search_path": schema}
        elif "mysql+aiomysql" in self.db_url:
            if self.ssl_verify:
                connect_args["ssl"] = True
            # For MySQL, schema is natively isolated via the database catalog name in the URL,
            # but we can also set init_command if needed.

        engine_kwargs = {
            "pool_pre_ping": True,
            "pool_recycle": 3600,
        }
        
        # SQLite memory databases do not support pooling size/overflow params
        if "sqlite" not in self.db_url:
            engine_kwargs["pool_size"] = 10
            engine_kwargs["max_overflow"] = 20

        if connect_args:
            engine_kwargs["connect_args"] = connect_args

        self.engine = create_async_engine(
            self.db_url,
            **engine_kwargs
        )
        self.session_factory = async_sessionmaker(
            self.engine,
            expire_on_commit=False,
            class_=AsyncSession
        )

    async def verify_connection_with_retry(self) -> None:
        """Verifies database connectivity with exponential backoff and jitter."""
        max_attempts = 5
        base_delay = 2.0
        
        for attempt in range(1, max_attempts + 1):
            try:
                async with self.engine.connect() as conn:
                    await conn.execute(text("SELECT 1"))
                logger.info("Successfully connected to the database.")
                return
            except Exception as e:
                # Add jitter (+/- 0.5 seconds)
                jitter = random.uniform(-0.5, 0.5)
                delay = (base_delay * (2 ** (attempt - 1))) + jitter
                delay = max(0.1, delay) # Ensure positive delay
                
                logger.warning(
                    f"Database connection attempt {attempt} failed: {e}. "
                    f"Retrying in {delay:.2f} seconds..."
                )
                if attempt == max_attempts:
                    logger.critical("Could not connect to database after maximum retries.")
                    raise DatabaseConnectionError(f"Database unavailable: {e}")
                await asyncio.sleep(delay)

    @asynccontextmanager
    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """Provides a fail-closed transaction session context manager."""
        if not self.session_factory:
            raise RuntimeError("Database connection engine is not initialized.")
        session = self.session_factory()
        try:
            yield session
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.error(f"Transaction rolled back due to error: {e}")
            raise
        finally:
            await session.close()

    async def close(self) -> None:
        if self.engine:
            await self.engine.dispose()
            logger.info("Database engine connections disposed.")
