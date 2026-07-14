from typing import TypedDict, List, Dict, Any

class AgentState(TypedDict):
    repo_name: str             # Name of the repository
    vcs_url: str               # VCS URL of the repository
    feature_request: str       # Conversational prompt submitted by PM
    chat_history: List[Dict[str, str]] # Full conversation history
    is_clear: bool             # Flag determining if requirements are clear
    clarifying_question: str   # Generated question if not clear
    rules: List[Dict[str, Any]]# List of rules passed from the server
    parsed_intent: Dict[str, Any]  # Intent JSON containing keywords, directories, file_types
    search_queries: List[str]  # Query strings executed on search connectors
    search_results: List[Dict[str, Any]] # Matches returned by Search connectors
    matching_rules: List[Dict[str, Any]] # Rules triggered by search matches
    final_report: str          # Generated markdown PRD report
    logs: List[Dict[str, Any]] # History of SSE trace events
