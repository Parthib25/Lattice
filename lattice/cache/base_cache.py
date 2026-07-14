from abc import ABC, abstractmethod
from typing import Optional

class CacheManager(ABC):
    @abstractmethod
    async def get(self, key: str) -> Optional[str]:
        """Retrieves a string value from the cache. Returns None on miss/expiry."""
        pass

    @abstractmethod
    async def set(self, key: str, value: str, ttl: int = 3600) -> None:
        """Saves a string value under a key with a Time-To-Live in seconds."""
        pass

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Deletes a key from the cache."""
        pass

    @abstractmethod
    async def clear(self) -> None:
        """Clears all cached keys (for testing and manual reset)."""
        pass
