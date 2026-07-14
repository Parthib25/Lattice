import pytest
from typing import List, Optional
from lattice.agent import compile_glob_to_regex, LatticeAgent
from lattice.connectors import LLMConnector, SearchConnector, SearchResult

# Mock LLM Connector
class MockLLMConnector(LLMConnector):
    def __init__(self, should_fail: bool = False):
        self.should_fail = should_fail
        
    async def generate_response(self, prompt: str, system_instruction: Optional[str] = None, **kwargs) -> str:
        if self.should_fail:
            raise RuntimeError("API failure")
            
        # Parse intent response mock
        if "JSON" in (system_instruction or ""):
            return '{"keywords": ["billing", "csv"], "directories": ["/backend"], "file_types": [".py"]}'
            
        # Feasibility report response mock
        return "# Feasibility Report\n- Status: Partially Blocked\n- Reason: Billing files require reviews."


# Mock Search Connector
class MockSearchConnector(SearchConnector):
    async def search(self, query: str, repo_path: str) -> List[SearchResult]:
        return [
            {
                "path": "backend/payments/controllers/Billing.py",
                "matched_lines": ["def download_csv():"],
                "line_numbers": [42]
            }
        ]


def test_glob_to_regex_translation():
    """Verify that path globs compile to correct regular expressions (exact, prefix, middle)."""
    # 1. Prefix Wildcard
    regex1 = compile_glob_to_regex("/backend/payments/*")
    assert regex1.match("/backend/payments/controllers/Billing.py") is not None
    assert regex1.match("/backend/payments/models.py") is not None
    assert regex1.match("/frontend/payments/index.js") is None
    assert regex1.match("/backend/auth/login.py") is None

    # 2. Middle Wildcard
    regex2 = compile_glob_to_regex("/backend/*/controllers/*.py")
    assert regex2.match("/backend/billing/controllers/billing_controller.py") is not None
    assert regex2.match("/backend/billing/models/billing.py") is None

    # 3. Exact Match
    regex3 = compile_glob_to_regex("/package.json")
    assert regex3.match("/package.json") is not None
    assert regex3.match("/server/package.json") is None


@pytest.mark.asyncio
async def test_agent_graph_execution():
    """Verifies complete LangGraph state machine node sequencing with logs callback hooks."""
    events = []
    def log_callback(event_dict):
        events.append(event_dict)

    llm = MockLLMConnector()
    searcher = MockSearchConnector()
    agent = LatticeAgent(llm, searcher, log_callback=log_callback)

    # Active rules passed by server
    rules = [
        {
            "id": "rule-1",
            "protected_paths": ["/backend/payments/*"],
            "rule_type": "BLOCK",
            "guardrail_message": "Block changes to Payments"
        }
    ]

    result = await agent.run(
        feature_request="Add download CSV button to billing payments page",
        rules=rules
    )

    # Verify final states
    assert result["parsed_intent"]["keywords"] == ["billing", "csv"]
    assert len(result["search_results"]) == 1
    assert result["search_results"][0]["path"] == "backend/payments/controllers/Billing.py"
    assert len(result["matching_rules"]) == 1
    assert result["matching_rules"][0]["rule_id"] == "rule-1"
    assert "Feasibility Report" in result["final_report"]

    # Verify SSE logs callback events
    assert len(events) > 0
    # Check that events contain node start/completes
    start_events = [e["node"] for e in events if e["event"] == "node_start"]
    complete_events = [e["node"] for e in events if e["event"] == "node_complete"]
    assert "parse" in start_events
    assert "search" in start_events
    assert "evaluate" in start_events
    assert "synthesize" in start_events
    assert "parse" in complete_events
    assert "search" in complete_events
    assert "evaluate" in complete_events
    assert "synthesize" in complete_events
