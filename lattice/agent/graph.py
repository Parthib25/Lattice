import re
import json
import logging
from typing import Optional, Callable, Dict, Any, List
from pydantic import BaseModel, Field
from langgraph.graph import StateGraph, END
from lattice.connectors import LLMConnector, SearchConnector
from lattice.agent.state import AgentState

logger = logging.getLogger("lattice.agent.graph")

class ParsedIntentModel(BaseModel):
    keywords: List[str] = Field(default_factory=list, description="Extracted search queries")
    directories: List[str] = Field(default_factory=list, description="Scoped directories if mentioned")
    file_types: List[str] = Field(default_factory=list, description="Target file extensions if specified")

class ClarifyResponseModel(BaseModel):
    vagueness_score: int = Field(description="Score from 1 to 5 based on the Vagueness Scoring Rubric using SMART criteria.")
    is_clear: bool = Field(description="True if vagueness_score >= 4, False if it needs more detail.")
    clarifying_question: str = Field(description="If is_clear is False, provide a question to ask the user. Otherwise empty string.")


def compile_glob_to_regex(pattern: str) -> re.Pattern:
    """Translates a glob wildcard pattern into a case-sensitive regular expression."""
    # Escape standard regex metacharacters
    escaped = re.escape(pattern)
    # Translate escaped asterisks back to match any sequence of characters
    # Since re.escape escapes '*', it becomes '\\*' in the escaped string
    regex_str = escaped.replace(r"\*", ".*")
    # Add anchors to force complete string matches
    return re.compile(f"^{regex_str}$")


class LatticeAgent:
    def __init__(
        self,
        llm: LLMConnector,
        searcher: SearchConnector,
        log_callback: Optional[Callable[[Dict[str, Any]], None]] = None
    ):
        self.llm = llm
        self.searcher = searcher
        self.log_callback = log_callback
        self.graph = self._compile_graph()

    def _emit_log(self, event: str, node: str, message: str, details: Optional[Dict[str, Any]] = None):
        """Helper to invoke callback logging trace events."""
        if self.log_callback:
            try:
                self.log_callback({
                    "event": event,
                    "node": node,
                    "message": message,
                    "details": details or {}
                })
            except Exception as e:
                logger.warning(f"Failed to execute logging callback: {e}")

    def _compile_graph(self):
        builder = StateGraph(AgentState)
        
        # Register nodes
        builder.add_node("clarify", self.node_clarify)
        builder.add_node("parse", self.node_parse)
        builder.add_node("search", self.node_search)
        builder.add_node("evaluate", self.node_evaluate)
        builder.add_node("synthesize", self.node_synthesize)
        
        # Set transitions
        builder.set_entry_point("parse")
        
        def route_clarify(state: AgentState):
            if state.get("is_clear"):
                return "evaluate"
            return END
            
        builder.add_edge("parse", "search")
        builder.add_edge("search", "clarify")
        builder.add_conditional_edges("clarify", route_clarify)
        builder.add_edge("evaluate", "synthesize")
        builder.add_edge("synthesize", END)
        
        return builder.compile()

    async def node_clarify(self, state: AgentState) -> Dict[str, Any]:
        self._emit_log("node_start", "clarify", "Evaluating clarity of requirements...")
        
        system_instruction = (
            "You are an expert technical product manager. Review the chat history and determine if the current feature request "
            "is clear enough to assess technical feasibility in a codebase. "
            "Score the requirement on vagueness using a structured rubric based on the SMART criteria (Specific, Measurable, Achievable, Relevant, Time-bound).\n"
            "The Vagueness Scoring Rubric (1-5 Scale):\n"
            "5 - Highly Specific & Actionable: Completely unambiguous. Identifies exact actor, action, and target without subjective terms. Includes quantifiable metrics and baseline data.\n"
            "4 - Generally Clear (Minor Refinements Needed): Core goal is understood and quantifiable, but may be missing specific conditions or strict timeline.\n"
            "3 - Moderately Vague (Lacks specific metrics/scope, needs structural refinement): Missing key components of SMART. Has a general direction but leaves room for multiple interpretations.\n"
            "2 - Highly Vague (Broad problem statement, no solution): Very abstract. No clear target, timeline, or measurable outcome.\n"
            "1 - Unactionable/Critically Vague: Just an idea or complaint. Needs complete elicitation.\n\n"
            "If the score is >= 4, set is_clear to true and clarifying_question to an empty string. "
            "If the score is <= 3, set is_clear to false and provide one or more concise clarifying questions to improve the score. "
            "Output ONLY a valid JSON object matching this schema:\n"
            "{\n"
            "  \"vagueness_score\": integer,\n"
            "  \"is_clear\": boolean,\n"
            "  \"clarifying_question\": \"your question(s) here\"\n"
            "}\n"
            "Do not include markdown tags or extra text."
        )
        
        # Format history
        history_text = "\n".join([f"{msg['role'].capitalize()}: {msg['content']}" for msg in state.get('chat_history', [])])
        
        # Include search results
        search_hits = state.get('search_results', [])
        search_context = "No relevant codebase context found."
        if search_hits:
            search_context = json.dumps(search_hits, indent=2)
            
        repo_name = state.get('repo_name', 'Unknown Repository')
        prompt = f"Target Repository: {repo_name}\n\nChat History:\n{history_text}\n\nCodebase Search Context:\n{search_context}\n\nEvaluate clarity."
        
        result = {"vagueness_score": 5, "is_clear": True, "clarifying_question": ""}
        try:
            response = await self.llm.generate_response(prompt, system_instruction=system_instruction)
            clean_res = response.strip()
            if clean_res.startswith("```"):
                lines = clean_res.split("\n")
                if lines[0].startswith("```json") or lines[0].startswith("```"):
                    clean_res = "\n".join(lines[1:-1]).strip()
                    
            model = ClarifyResponseModel.model_validate_json(clean_res)
            result = model.model_dump()
        except Exception as e:
            logger.error(f"Error parsing LLM response in node_clarify: {e}")
            raise RuntimeError(f"Downstream LLM API error in clarify node: {e}")
            
        self._emit_log(
            "node_complete", "clarify", 
            "Requirement is clear." if result["is_clear"] else f"Asking for clarification: {result['clarifying_question']}",
            details={"is_clear": result["is_clear"], "vagueness_score": result.get("vagueness_score")}
        )
        
        return result

    async def node_parse(self, state: AgentState) -> Dict[str, Any]:
        self._emit_log("node_start", "parse", "Parsing raw feature request intent...")
        
        system_instruction = (
            "You are an expert system parser. Output ONLY a valid JSON object fitting this schema:\n"
            "{\n"
            "  \"keywords\": [\"list\", \"of\", \"search\", \"terms\"],\n"
            "  \"directories\": [\"optional\", \"directories\"],\n"
            "  \"file_types\": [\"optional\", \"extensions\"]\n"
            "}\n"
            "Do not include markdown tags, code blocks, or extra text."
        )
        history_text = "\n".join([f"{msg['role'].capitalize()}: {msg['content']}" for msg in state.get('chat_history', [])])
        repo_name = state.get('repo_name', 'Unknown Repository')
        prompt = f"Target Repository: {repo_name}\n\nAnalyze the following conversation history and extract the target feature request keywords/parameters:\n{history_text}"
        
        parsed_intent = {"keywords": [], "directories": [], "file_types": []}
        try:
            response = await self.llm.generate_response(prompt, system_instruction=system_instruction)
            # Remove markdown backticks if returned
            clean_res = response.strip()
            if clean_res.startswith("```"):
                lines = clean_res.split("\n")
                if lines[0].startswith("```json") or lines[0].startswith("```"):
                    clean_res = "\n".join(lines[1:-1]).strip()
            
            # Validate output structure via Pydantic
            model = ParsedIntentModel.model_validate_json(clean_res)
            parsed_intent = model.model_dump()
        except Exception as e:
            logger.error(f"Error parsing LLM response in node_parse: {e}. Falling back to defaults.")
            # Fallback to extract keywords from request using basic tokenization
            # Use either the last message or feature_request if history is empty
            text_to_parse = state['feature_request']
            history = state.get('chat_history', [])
            if history:
                text_to_parse = " ".join([m['content'] for m in history if m['role'] == 'user'])
            words = [w.strip("?,.!") for w in text_to_parse.split() if len(w) > 3]
            parsed_intent["keywords"] = list(set(words[:5]))
            
        self._emit_log(
            "node_complete", "parse", "Intent parsed successfully.",
            details={"parsed_intent": parsed_intent}
        )
        return {"parsed_intent": parsed_intent}

    async def node_search(self, state: AgentState) -> Dict[str, Any]:
        intent = state["parsed_intent"]
        keywords = intent.get("keywords", [])
        
        # If no keywords were parsed, use the raw request string as query
        if not keywords:
            keywords = [state["feature_request"]]
            
        repo_name = state.get("repo_name", "repository")
        self._emit_log(
            "node_start", "search", f"Searching codebase {repo_name} indexes for: {', '.join(keywords)}..."
        )
        
        search_results = []
        search_queries = []
        for kw in keywords:
            search_queries.append(kw)
            logger.info(f"Executing search query: '{kw}' in repository '{repo_name}'")
            try:
                # Check if we are using GitHub to scope properly
                vcs_url = state.get("vcs_url", "")
                is_github = "github.com/" in vcs_url
                
                target_repo = ""
                if is_github:
                    target_repo = vcs_url.split("github.com/")[-1].strip("/")
                    if target_repo.endswith(".git"):
                        target_repo = target_repo[:-4]
                else:
                    target_repo = state.get("repo_name", "")

                # Scoping search to directories if specified (DISABLED per user request)
                # paths = intent.get("directories", [])
                
                search_kw = kw
                if is_github:
                    # Convert spaces in the keyword phrase to ' OR ' for a loose search
                    search_kw = " OR ".join(kw.split())
                    
                results = await self.searcher.search(search_kw, repo_path=target_repo)
                
                logger.info(f"Search query '{search_kw}' returned {len(results)} results:")
                for res in results:
                    logger.info(f" - Match in file: {res['path']}")
                    
                search_results.extend(results)
            except Exception as e:
                logger.error(f"Search connector error: {e}")
                
        # Deduplicate search matches by file path
        unique_results = {}
        for r in search_results:
            path = r["path"]
            if path not in unique_results:
                unique_results[path] = r
            else:
                # Merge matches
                unique_results[path]["matched_lines"].extend(r["matched_lines"])
                unique_results[path]["line_numbers"].extend(r["line_numbers"])
                
        results_list = list(unique_results.values())
        
        self._emit_log(
            "node_complete", "search", f"Code search completed. Found matches in {len(results_list)} files.",
            details={"search_results_count": len(results_list), "matching_paths": list(unique_results.keys())}
        )
        return {"search_queries": search_queries, "search_results": results_list}

    async def node_evaluate(self, state: AgentState) -> Dict[str, Any]:
        self._emit_log("node_start", "evaluate", "Evaluating repository guardrails and dependency rules...")
        
        rules = state.get("rules", [])
        search_results = state.get("search_results", [])
        feature_request_lower = state["feature_request"].lower()
        
        matching_rules = []
        for r in rules:
            rule_matched = False
            matched_reason = ""
            
            # Check 1: Keyword trigger check in raw request or search results matched lines
            keywords = r.get("keywords", [])
            for kw in keywords:
                if kw in feature_request_lower:
                    rule_matched = True
                    matched_reason = f"Keyword '{kw}' found in feature request prompt"
                    break
                
                # Check keyword in search result snippets
                for sr in search_results:
                    for line in sr.get("matched_lines", []):
                        if kw in line.lower():
                            rule_matched = True
                            matched_reason = f"Keyword '{kw}' found in file match: {sr['path']}"
                            break
                    if rule_matched:
                        break
            
            # Check 2: Directory/File path glob pattern match
            paths = r.get("protected_paths", [])
            if not rule_matched and paths:
                for path_pattern in paths:
                    try:
                        pattern_re = compile_glob_to_regex(path_pattern)
                        for sr in search_results:
                            file_path = sr["path"]
                            norm_path = file_path if file_path.startswith("/") else f"/{file_path}"
                            if pattern_re.match(norm_path) or pattern_re.match(file_path):
                                rule_matched = True
                                matched_reason = f"Protected path '{path_pattern}' matched file: {file_path}"
                                break
                    except Exception as e:
                        logger.error(f"Failed to compile glob regex '{path_pattern}': {e}")
                    if rule_matched:
                        break
            
            if rule_matched:
                matching_rules.append({
                    "rule_id": r.get("id") or r.get("component"),
                    "path_pattern": ", ".join(r.get("protected_paths", [])) or "Keyword-based",
                    "rule_type": r.get("rule_type", "INFORM"),
                    "guardrail_message": f"{r.get('guardrail_message', '')} ({matched_reason})",
                    "matched_file": r.get("owning_team", "Unknown Team")
                })
                
        # Deduplicate matching rules
        unique_matches = {}
        for m in matching_rules:
            key = (m["rule_id"], m["matched_file"])
            unique_matches[key] = m
            
        matches_list = list(unique_matches.values())
        
        repo_name = state.get("repo_name", "repository")
        self._emit_log(
            "node_complete", "evaluate", f"Guardrail check complete. Triggered {len(matches_list)} dependency rules.",
            details={"repo_name": repo_name, "matching_rules_count": len(matches_list), "rules_triggered": matches_list}
        )
        return {"matching_rules": matches_list}

    async def node_synthesize(self, state: AgentState) -> Dict[str, Any]:
        self._emit_log("node_start", "synthesize", "Synthesizing finalized feasibility report...")
        
        history_text = "\n".join([f"{msg['role'].capitalize()}: {msg['content']}" for msg in state.get('chat_history', [])])
        repo_name = state.get('repo_name', 'Unknown Repository')
        prompt = (
            f"Target Repository: {repo_name}\n\n"
            f"Generate a feasibility assessment report in Markdown for the following feature request conversation:\n"
            f"Conversation:\n{history_text}\n\n"
            f"Code Search Hits:\n{json.dumps(state['search_results'], indent=2)}\n\n"
            f"Triggered Dependency Rules:\n{json.dumps(state['matching_rules'], indent=2)}\n\n"
            f"List target file modifications and summarize approval constraints."
        )
        
        system_instruction = (
            "You are a Senior Product Architect. Synthesize a clean, professional, and visually structured "
            "Markdown feasibility report.\n"
            "The report MUST be structured with the following exact categories:\n"
            "1. What can be implemented\n"
            "2. What can be implemented if guardrails are met\n"
            "3. What cannot be implemented\n"
            "\n"
            "CRITICAL INSTRUCTION: If any point is inspired from the codebase, you MUST include clear citations of the codebase/sources inline. "
            "Clearly highlight blocked changes and team approval requirements. "
            "Do not output wrapping decorators, just output the markdown text."
        )
        
        final_report = "Unable to generate feasibility report due to downstream LLM connection error."
        try:
            final_report = await self.llm.generate_response(prompt, system_instruction=system_instruction)
        except Exception as e:
            logger.error(f"Error generating report: {e}")
            raise RuntimeError(f"Downstream LLM API error in synthesize node: {e}")
            
        self._emit_log(
            "node_complete", "synthesize", "Feasibility report synthesized successfully.",
            details={"final_report_preview": final_report[:200] + "..."}
        )
        return {"final_report": final_report}

    async def run(self, feature_request: str, rules: List[Dict[str, Any]], chat_history: List[Dict[str, str]] = None, repo_name: str = "repository", vcs_url: str = "") -> Dict[str, Any]:
        """Runs the LangGraph agent execution and returns the final state."""
        inputs = {
            "repo_name": repo_name,
            "vcs_url": vcs_url,
            "feature_request": feature_request,
            "chat_history": chat_history or [],
            "rules": rules,
            "parsed_intent": {},
            "search_queries": [],
            "search_results": [],
            "matching_rules": [],
            "final_report": "",
            "logs": []
        }
        
        # Enforce recursion limit config
        config = {"recursion_limit": 10}
        return await self.graph.ainvoke(inputs, config=config)
