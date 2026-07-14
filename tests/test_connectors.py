import asyncio
import fnmatch
import time
import pytest
from typing import List
from hypothesis import given, strategies as st, settings
import httpx
from lattice.cache import InMemoryCacheManager
from lattice.connectors import get_llm_connector, get_search_connector, retry_async, ConnectorConnectionError

# Setup simple mock server details
OLLAMA_HOST = "http://localhost:11434"

# Strategies for Hypothesis PBT
cache_key_strategy = st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd')))
cache_val_strategy = st.text(min_size=1, max_size=500, alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd', 'Zs')))
path_segment_strategy = st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=('Lu', 'Ll')))

@pytest.mark.asyncio
@given(k=cache_key_strategy, v=cache_val_strategy)
@settings(max_examples=20, deadline=None)
async def test_pbt_in_memory_cache_roundtrip(k, v):
    """PBT verifying in-memory cache read/write round-trip (PBT-02)."""
    cache = InMemoryCacheManager()
    
    # Assert missing key returns None
    assert await cache.get(k) is None
    
    # Write to cache
    await cache.set(k, v, ttl=100)
    
    # Read back and assert identity
    assert await cache.get(k) == v
    
    # Delete and assert None
    await cache.delete(k)
    assert await cache.get(k) is None

@pytest.mark.asyncio
async def test_in_memory_cache_expiry():
    cache = InMemoryCacheManager()
    await cache.set("temp", "value", ttl=-1) # Immediate expiry
    assert await cache.get("temp") is None

@pytest.mark.asyncio
@given(
    team_name=path_segment_strategy,
    sub_name=path_segment_strategy,
    file_name=path_segment_strategy
)
@settings(max_examples=20, deadline=None)
async def test_pbt_path_wildcard_matching(team_name, sub_name, file_name):
    """PBT verifying glob path pattern checking invariants using fnmatch (PBT-03)."""
    # Normalize segment characters
    t = team_name.lower()
    s = sub_name.lower()
    f = file_name.lower()
    
    pattern1 = f"/backend/{t}/*"
    pattern2 = f"/backend/{t}/{s}/*.py"
    
    match_path1 = f"/backend/{t}/controllers/billing.py"
    match_path2 = f"/backend/{t}/{s}/{f}.py"
    mismatch_path = "/frontend/components/App.tsx"
    
    assert fnmatch.fnmatchcase(match_path1, pattern1) is True
    assert fnmatch.fnmatchcase(match_path2, pattern2) is True
    assert fnmatch.fnmatchcase(mismatch_path, pattern1) is False
    assert fnmatch.fnmatchcase(mismatch_path, pattern2) is False

@pytest.mark.asyncio
async def test_connector_retry_failure():
    """Verify that the retry_async decorator correctly bubbles exception after 3 tries."""
    call_count = 0
    
    @retry_async(max_attempts=3, base_delay=0.01)
    async def failing_api():
        nonlocal call_count
        call_count += 1
        raise httpx.ConnectError("Connection timed out")

    with pytest.raises(ConnectorConnectionError) as exc_info:
        await failing_api()
        
    assert "Failed to communicate with external provider" in str(exc_info.value)
    assert call_count == 3


@pytest.mark.asyncio
async def test_custom_llm_and_search_connectors_registration():
    """Verify dynamic registry and factory loading for custom LLM and Search extensions (OCP/DIP)."""
    from lattice.connectors import (
        register_custom_llm_provider,
        register_custom_search_provider,
        LLMConnector,
        SearchConnector,
        SearchResult
    )

    # 1. Custom LLM Provider implementation
    class CustomLLM(LLMConnector):
        def __init__(self, api_key=None, model=None, base_url=None):
            self.model = model

        async def generate_response(self, prompt: str, system_instruction=None, **kwargs) -> str:
            return f"Custom response from {self.model}: {prompt}"

    # 2. Custom Search Provider implementation
    class CustomSearch(SearchConnector):
        def __init__(self, token=None, endpoint_url=None, base_path=None):
            pass

        async def search(self, query: str, repo_path: str) -> List[SearchResult]:
            return [{
                "path": "custom/path.py",
                "matched_lines": [f"Custom search match: {query}"],
                "line_numbers": [99]
            }]

    # Register providers
    register_custom_llm_provider("my-custom-llm", CustomLLM)
    register_custom_search_provider("my-custom-search", CustomSearch)

    # Resolve connectors using factory functions
    llm = get_llm_connector("my-custom-llm", model="custom-gpt-v1")
    searcher = get_search_connector("my-custom-search", base_path=".")

    res_llm = await llm.generate_response("hello")
    res_search = await searcher.search("query", "repo")

    assert res_llm == "Custom response from custom-gpt-v1: hello"
    assert len(res_search) == 1
    assert res_search[0]["path"] == "custom/path.py"


@pytest.mark.asyncio
async def test_github_search_connector_query(respx_mock=None):
    """Verify GitHub Code Search REST API integration connector queries."""
    from lattice.connectors.providers_search import GitHubSearchConnector

    connector = GitHubSearchConnector(token="github-token", endpoint_url="https://api.github.com")

    # If mock helper is active or we mock the request client
    # Let's mock the httpx client request using unittest.mock patch
    from unittest.mock import AsyncMock, patch

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json = MagicMock(return_value={
        "items": [
            {"path": "src/auth/bouncer.py"},
            {"path": "lib/auth/utils.js"}
        ]
    })

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp):
        results = await connector.search("bouncer", "org/repo")

    assert len(results) == 2
    assert results[0]["path"] == "src/auth/bouncer.py"
    assert results[1]["path"] == "lib/auth/utils.js"
    assert "GitHub" in results[0]["matched_lines"][0]


from unittest.mock import MagicMock
