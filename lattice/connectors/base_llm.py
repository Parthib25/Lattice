import asyncio
import logging
import random
from abc import ABC, abstractmethod
from typing import Optional, Callable, Any

logger = logging.getLogger("lattice.connectors.base_llm")

class ConnectorConnectionError(Exception):
    """Raised when an external API connection fails permanently after retries."""
    pass

def retry_async(max_attempts: int = 3, base_delay: float = 1.0) -> Callable:
    """Decorator to retry an async function with exponential backoff and jitter on exceptions."""
    def decorator(func: Callable) -> Callable:
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    # Don't retry on user errors, raise immediately if needed
                    # For this generic retry we retry on all exceptions (network, 500, etc.)
                    jitter = random.uniform(-0.2, 0.2)
                    delay = (base_delay * (2 ** (attempt - 1))) + jitter
                    delay = max(0.1, delay)
                    
                    logger.warning(
                        f"External API call failed in {func.__name__} (attempt {attempt}/{max_attempts}): {e}. "
                        f"Retrying in {delay:.2f}s..."
                    )
                    if attempt == max_attempts:
                        raise ConnectorConnectionError(
                            f"Failed to communicate with external provider after {max_attempts} attempts. Error: {e}"
                        )
                    await asyncio.sleep(delay)
        return wrapper
    return decorator


class LLMConnector(ABC):
    @abstractmethod
    async def generate_response(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        **kwargs
    ) -> str:
        """Sends prompt to the model and returns text output.
        
        Custom execution options can be dynamically passed via kwargs.
        """
        pass
