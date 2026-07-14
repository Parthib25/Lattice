from typing import Optional, Dict, Type
from lattice.connectors.base_llm import LLMConnector, ConnectorConnectionError, retry_async
from lattice.connectors.base_search import SearchConnector, SearchResult
from lattice.connectors.providers_llm import (
    OpenAIConnector,
    AnthropicConnector,
    GeminiConnector,
    OllamaConnector,
    HuggingFaceConnector,
)
from lattice.connectors.providers_search import (
    GitHubSearchConnector,
    SourcegraphConnector,
    LocalFolderScanner,
)

# Registries for dynamic custom connectors extensions (OCP/DIP)
_CUSTOM_LLM_PROVIDERS: Dict[str, Type[LLMConnector]] = {}
_CUSTOM_SEARCH_PROVIDERS: Dict[str, Type[SearchConnector]] = {}


def register_custom_llm_provider(name: str, provider_cls: Type[LLMConnector]) -> None:
    """Registers a custom LLM connector class under a lookup name."""
    _CUSTOM_LLM_PROVIDERS[name.lower()] = provider_cls


def register_custom_search_provider(name: str, provider_cls: Type[SearchConnector]) -> None:
    """Registers a custom Search connector class under a lookup name."""
    _CUSTOM_SEARCH_PROVIDERS[name.lower()] = provider_cls


def get_llm_connector(
    provider: str,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    base_url: Optional[str] = None
) -> LLMConnector:
    """Factory helper to build LLM connector instances based on parameters."""
    prov_lower = provider.lower()
    
    # Check custom provider map first to support extensions
    if prov_lower in _CUSTOM_LLM_PROVIDERS:
        custom_cls = _CUSTOM_LLM_PROVIDERS[prov_lower]
        # Instantiate custom provider passing variables as kwargs
        return custom_cls(api_key=api_key, model=model, base_url=base_url)
    
    if prov_lower == "openai":
        key = api_key or ""
        mdl = model or "gpt-4o"
        url = base_url or "https://api.openai.com/v1"
        return OpenAIConnector(api_key=key, model=mdl, base_url=url)
        
    elif prov_lower == "anthropic":
        key = api_key or ""
        mdl = model or "claude-3-5-sonnet-20240620"
        url = base_url or "https://api.anthropic.com/v1"
        return AnthropicConnector(api_key=key, model=mdl, base_url=url)
        
    elif prov_lower == "gemini":
        key = api_key or ""
        mdl = model or "gemini-3.5-flash"
        url = base_url or "https://generativelanguage.googleapis.com/v1beta"
        return GeminiConnector(api_key=key, model=mdl, base_url=url)
        
    elif prov_lower == "ollama":
        mdl = model or "llama3"
        url = base_url or "http://localhost:11434"
        return OllamaConnector(model=mdl, base_url=url)
        
    elif prov_lower == "huggingface":
        key = api_key or ""
        mdl = model or "meta-llama/Meta-Llama-3-8B-Instruct"
        url = base_url or "https://api-inference.huggingface.co/models"
        return HuggingFaceConnector(api_key=key, model=mdl, base_url=url)
        
    else:
        raise ValueError(f"Unknown LLM provider: {provider}")


def get_search_connector(
    provider: str,
    base_path: str,
    token: Optional[str] = None,
    endpoint_url: Optional[str] = None
) -> SearchConnector:
    """Factory helper to build code search connector instances."""
    prov_lower = provider.lower()
    
    # Check custom provider map first to support extensions
    if prov_lower in _CUSTOM_SEARCH_PROVIDERS:
        custom_cls = _CUSTOM_SEARCH_PROVIDERS[prov_lower]
        return custom_cls(token=token, endpoint_url=endpoint_url, base_path=base_path)
    
    if prov_lower == "sourcegraph":
        tok = token or ""
        url = endpoint_url or "https://sourcegraph.com"
        return SourcegraphConnector(token=tok, endpoint_url=url)
    elif prov_lower == "github":
        tok = token or ""
        url = endpoint_url or "https://api.github.com"
        return GitHubSearchConnector(token=tok, endpoint_url=url)
    elif prov_lower == "local":
        return LocalFolderScanner(base_path=base_path)
    else:
        raise ValueError(f"Unknown search provider: {provider}")


__all__ = [
    "LLMConnector",
    "ConnectorConnectionError",
    "retry_async",
    "SearchConnector",
    "SearchResult",
    "OpenAIConnector",
    "AnthropicConnector",
    "GeminiConnector",
    "OllamaConnector",
    "HuggingFaceConnector",
    "SourcegraphConnector",
    "GitHubSearchConnector",
    "LocalFolderScanner",
    "get_llm_connector",
    "get_search_connector",
    "register_custom_llm_provider",
    "register_custom_search_provider",
]
