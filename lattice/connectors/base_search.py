from abc import ABC, abstractmethod
from typing import List, TypedDict

class SearchResult(TypedDict):
    path: str               # File path relative to repository/workspace root
    matched_lines: List[str]  # Matching lines content snippets
    line_numbers: List[int]   # Corresponding line numbers (1-indexed)

class SearchConnector(ABC):
    @abstractmethod
    async def search(self, query: str, repo_path: str) -> List[SearchResult]:
        """Searches a directory or codebase index for string query occurrences.
        
        Returns a list of structured SearchResult objects.
        """
        pass
