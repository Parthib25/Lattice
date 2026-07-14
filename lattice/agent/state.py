from typing import TypedDict, List, Dict, Any

class AgentState(TypedDict):
    feature_request: str       # Conversational prompt submitted by PM
    rules: List[Dict[str, Any]]# List of rules passed from the server
    parsed_intent: Dict[str, Any]  # Intent JSON containing keywords, directories, file_types
    search_queries: List[str]  # Query strings executed on search connectors
    search_results: List[Dict[str, Any]] # Matches returned by Search connectors
    matching_rules: List[Dict[str, Any]] # Rules triggered by search matches
    final_report: str          # Generated markdown PRD report
    logs: List[Dict[str, Any]] # History of SSE trace events
