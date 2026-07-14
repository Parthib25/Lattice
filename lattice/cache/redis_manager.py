import time
import logging
from typing import Optional, Dict, Tuple
from redis.asyncio import Redis, from_url
from lattice.cache.base_cache import CacheManager

logger = logging.getLogger("lattice.cache.redis_manager")

class InMemoryCacheManager(CacheManager):
    """Thread-safe fallback in-memory cache manager that respects TTLs."""
    def __init__(self):
        self._store: Dict[str, Tuple[str, float]] = {} # key -> (value, expiry_timestamp)
        logger.info("Initialized In-Memory Cache Manager fallback.")

    async def get(self, key: str) -> Optional[str]:
        if key not in self._store:
            return None
        val, expiry = self._store[key]
        if time.time() > expiry:
            # Lazy delete expired key
            self._store.pop(key, None)
            return None
        return val

    async def set(self, key: str, value: str, ttl: int = 3600) -> None:
        expiry = time.time() + ttl
        self._store[key] = (value, expiry)

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)

    async def clear(self) -> None:
        self._store.clear()


class RedisCacheManager(CacheManager):
    """Asynchronous production Redis cache manager."""
    def __init__(self, redis_url: str):
        self.redis_url = redis_url
        self.client: Optional[Redis] = None

    async def connect(self) -> bool:
        try:
            self.client = from_url(
                self.redis_url,
                socket_timeout=2.0,
                decode_responses=True
            )
            # Ping to verify connection
            await self.client.ping()
            logger.info("Successfully connected to Redis.")
            return True
        except Exception as e:
            logger.warning(f"Failed to connect to Redis: {e}. Falling back to in-memory.")
            self.client = None
            return False

    async def get(self, key: str) -> Optional[str]:
        if not self.client:
            return None
        try:
            return await self.client.get(key)
        except Exception as e:
            logger.error(f"Redis get error: {e}")
            return None

    async def set(self, key: str, value: str, ttl: int = 3600) -> None:
        if not self.client:
            return
        try:
            await self.client.set(key, value, ex=ttl)
        except Exception as e:
            logger.error(f"Redis set error: {e}")

    async def delete(self, key: str) -> None:
        if not self.client:
            return
        try:
            await self.client.delete(key)
        except Exception as e:
            logger.error(f"Redis delete error: {e}")

    async def clear(self) -> None:
        if not self.client:
            return
        try:
            await self.client.flushdb()
        except Exception as e:
            logger.error(f"Redis flushdb error: {e}")
            
    async def close(self) -> None:
        if self.client:
            await self.client.close()
            logger.info("Redis connection closed.")
