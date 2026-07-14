import os
import logging
from typing import List, Optional
import httpx
from lattice.connectors.base_search import SearchConnector, SearchResult

class GitHubSearchConnector(SearchConnector):
    """GitHub API Code Search Connector supporting authentication and repositories scoping."""
    def __init__(self, token: str, endpoint_url: str = "https://api.github.com"):
        self.token = token
        self.endpoint_url = endpoint_url.rstrip("/")

    async def search(self, query: str, repo_path: str) -> List[SearchResult]:
        """Runs a search query against GitHub code search APIs."""
        headers = {
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json"
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        # Setup request path matching syntax
        # repo_path should be specified in org/repo format
        search_query = query
        if repo_path:
            search_query = f"repo:{repo_path} {query}"

        params = {"q": search_query}
        url = f"{self.endpoint_url}/search/code"

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=headers, params=params)
            response.raise_for_status()
            res_json = response.json()

            results: List[SearchResult] = []
            items = res_json.get("items", [])
            for item in items:
                file_path = item.get("path", "")
                # GitHub code search endpoint does not return text snippet previews natively
                # in the initial search listing body; we supply default summaries
                # (Users can override or fetch content directly in custom connectors)
                results.append({
                    "path": file_path,
                    "matched_lines": [f"Match found in GitHub repository: {file_path}"],
                    "line_numbers": [1]
                })

            return results


logger = logging.getLogger("lattice.connectors.providers_search")

class SourcegraphConnector(SearchConnector):
    """Sourcegraph API Search Provider supporting custom enterprise endpoints."""
    def __init__(self, token: str, endpoint_url: str = "https://sourcegraph.com"):
        self.token = token
        # Normalize endpoint URL to ensure /.api/graphql endpoint mapping
        self.endpoint_url = endpoint_url.rstrip("/")

    async def search(self, query: str, repo_path: str) -> List[SearchResult]:
        """Runs a search query on the Sourcegraph instance."""
        headers = {
            "Authorization": f"token {self.token}",
            "Content-Type": "application/json"
        }
        
        # GraphQL search query
        graphql_query = """
        query ($query: String!) {
          search(query: $query, version: Lucky) {
            results {
              results {
                ... on FileMatch {
                  file {
                    path
                  }
                  lineMatches {
                    lineNumber
                    preview
                  }
                }
              }
            }
          }
        }
        """
        
        # Formulate query scoped to repo if path is provided
        search_query = query
        if repo_path:
            # Sourcegraph repos are typically referenced by name (e.g. repo:^github\.com/owner/name$)
            search_query = f"repo:{repo_path} {query}"

        data = {
            "query": graphql_query,
            "variables": {"query": search_query}
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(f"{self.endpoint_url}/.api/graphql", headers=headers, json=data)
            response.raise_for_status()
            res_json = response.json()
            
            results: List[SearchResult] = []
            try:
                search_data = res_json["data"]["search"]["results"]["results"]
                for item in search_data:
                    # Check if result is a FileMatch
                    if "file" in item:
                        file_path = item["file"]["path"]
                        matched_lines = []
                        line_numbers = []
                        for lm in item.get("lineMatches", []):
                            matched_lines.append(lm["preview"])
                            line_numbers.append(lm["lineNumber"])
                        
                        results.append({
                            "path": file_path,
                            "matched_lines": matched_lines,
                            "line_numbers": line_numbers
                        })
            except (KeyError, TypeError) as e:
                logger.error(f"Error parsing Sourcegraph GraphQL response: {e}")
                
            return results


class LocalFolderScanner(SearchConnector):
    """Local workspace directory substring content search provider."""
    def __init__(self, base_path: str):
        self.base_path = os.path.abspath(base_path)
        self.ignore_dirs = {
            ".git", ".github", ".svn", "node_modules", "bower_components",
            ".venv", "venv", "env", "__pycache__", ".pytest_cache",
            "aidlc-docs", ".gemini", "brain"
        }
        self.supported_extensions = {
            ".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css",
            ".json", ".sql", ".md", ".toml", ".yaml", ".yml", ".txt"
        }
        self.max_file_size = 2 * 1024 * 1024 # 2MB

    async def search(self, query: str, repo_path: str = "") -> List[SearchResult]:
        """Scans the local directory for substring matches."""
        target_dir = self.base_path
        if repo_path:
            # Allow scoping search to a subdirectory representing a repository
            target_dir = os.path.abspath(os.path.join(self.base_path, repo_path))
            # Safety check to prevent directory traversal outside base path
            if not target_dir.startswith(self.base_path):
                target_dir = self.base_path

        results: List[SearchResult] = []
        query_lower = query.lower()

        # Walks directories recursively
        for root, dirs, files in os.walk(target_dir):
            # Exclude ignored directories in-place
            dirs[:] = [d for d in dirs if d not in self.ignore_dirs]
            
            for file in files:
                ext = os.path.splitext(file)[1]
                if ext not in self.supported_extensions:
                    continue
                
                full_path = os.path.join(root, file)
                try:
                    # Skip large files
                    if os.path.getsize(full_path) > self.max_file_size:
                        continue
                        
                    # Read content and search substring
                    with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                        lines = f.readlines()
                        
                    matched_lines = []
                    line_numbers = []
                    for idx, line in enumerate(lines, 1):
                        if query_lower in line.lower():
                            matched_lines.append(line.rstrip("\n"))
                            line_numbers.append(idx)
                            
                    if matched_lines:
                        # Extract relative path to base path
                        rel_path = os.path.relpath(full_path, self.base_path)
                        # Replace windows backslashes with forward slashes for consistency
                        rel_path = rel_path.replace("\\", "/")
                        results.append({
                            "path": rel_path,
                            "matched_lines": matched_lines,
                            "line_numbers": line_numbers
                        })
                except Exception as e:
                    logger.warning(f"Failed to scan file {file}: {e}")
                    
        return results
