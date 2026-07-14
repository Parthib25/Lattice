Feature Feasibility Agent: Architecture & Implementation GuideThis document outlines the architecture, database schema, and implementation strategy for building an open-source Feature Feasibility Agent. This agent is designed as a deployable Python library/server (similar to Headroom) that utilizes an agentic LLM loop to evaluate feature requests against semantically indexed codebases and organizational dependency rules.1. User JourneysThe system supports two distinct journeys: one for setting up the guardrails (Configuration) and one for utilizing the agent (Execution).1a. Configuration Journey (The Setup)Tech Leads, Engineering Managers, or Senior PMs use a web-based UI to manage user-level configurations and organizational rules.Authentication: The user logs into the Configuration Dashboard (Web UI).Integration Setup: The user connects the semantic search connector (e.g., Sourcegraph) and provides their LLM API keys (BYOK).Rule Definition: The user maps specific repository paths to their department (e.g., /backend/payments/*) and defines dependency rules (e.g., "Block PMs from changing this without backend approval").User Management: Admins can invite other PMs and assign them to specific departments, isolating their configuration access.1b. PM Chat Journey (The Execution)The primary user is a Product Manager (PM) lacking deep technical context. The goal is to refine raw feature requests into technically sound, feasible requirements before engineering begins.Initialization: The PM connects to the agent's Chat UI. The agent loads the user-specific configurations and department rules.Request Submission: The PM enters a natural language feature request (e.g., "Add a 'Download as CSV' button to the financial dashboard").Agentic Loop (The Q&A):Parsing: The LLM evaluates the request for completeness.Codebase Querying: The agent formulates semantic search queries to find relevant code paths.Dependency Checking: The agent cross-references the found code paths against the configuration database to determine team ownership and user-level constraints.Feedback: The agent reports back to the PM (Feasible, Dependencies required, or Blocked).Refinement: The PM converses with the agent to adjust the requirement based on these constraints.Output Generation: The agent synthesizes the finalized, technically validated scope into a structured User Journey/PRD format.2. System ArchitectureThe system is designed for high scalability and modularity, using a Bring Your Own Key (BYOK) model for both LLMs and Search Connectors.Core ComponentsAPI Server (FastAPI): Handles HTTP/WebSocket connections from the Chat UI and the Configuration Dashboard. Manages authentication, user sessions, and request routing.Web UI (React/Vue or Static Templates): A dual-purpose frontend serving the Chat Interface for PMs and the Settings Dashboard for user-level configuration management.Agent Engine (LangGraph): Orchestrates the state machine for the Q&A loop. Manages conversation memory and decides when to search, check rules, or ask the user.Code Search Connectors: Abstracted interface for semantic search.Config Database (PostgreSQL/MySQL): Stores user profiles, inter-department dependency rules, and repository configurations.Distributed Cache (Redis): Handles caching at multiple layers to ensure scalability under high traffic.Scalability & Caching StrategyTo handle high traffic, the architecture relies heavily on distributed caching (Redis):LLM Query Caching: Exact match or high-similarity prompts are cached to reduce LLM API calls, saving costs and lowering latency.Semantic Search Caching: Semantic search results for specific concepts are cached with a Time-To-Live (TTL) based on the repository's commit frequency.Config Caching: User rules and department boundaries are loaded into the cache and updated via pub/sub when the database changes, avoiding database hits for every agent evaluation step.Asynchronous Processing: LangGraph nodes and search connector calls must be fully asynchronous to prevent blocking the FastAPI event loop.BYOK (Bring Your Own Key) ModelThe architecture enforces strict separation of concerns via interfaces:LLM Interface: Supports OpenAI, Anthropic, or local models (via Ollama/vLLM) through a unified interface.Search Connector Interface: Supports Sourcegraph, Repowise, or Bloop via an abstract SemanticSearchProvider base class.3. Database SchemaThe schema manages users, organizational constraints, and dependency rules. It is designed to be compatible with both PostgreSQL and MySQL (using SQLAlchemy).-- Represents an organizational team
CREATE TABLE departments (
    id UUID PRIMARY KEY, -- CHAR(36) in MySQL
    name VARCHAR(100) UNIQUE NOT NULL,
    contact_handle VARCHAR(50) NOT NULL
);

-- Represents individual users (PMs, Tech Leads) using the system
CREATE TABLE users (
    id UUID PRIMARY KEY,
    username VARCHAR(100) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    department_id UUID REFERENCES departments(id),
    role VARCHAR(50) DEFAULT 'USER' -- 'ADMIN', 'LEAD', 'USER'
);

-- Represents a codebase
CREATE TABLE repositories (
    id UUID PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    vcs_url VARCHAR(255) NOT NULL
);

-- Maps file paths to owning teams (Configured via UI)
CREATE TABLE code_ownership (
    id UUID PRIMARY KEY,
    repo_id UUID REFERENCES repositories(id),
    owning_department_id UUID REFERENCES departments(id),
    path_pattern VARCHAR(255) NOT NULL,
    is_locked BOOLEAN DEFAULT FALSE,
    UNIQUE (repo_id, path_pattern)
);

-- Defines agent behavior when paths are touched (Configured via UI)
CREATE TABLE dependency_rules (
    id UUID PRIMARY KEY,
    code_ownership_id UUID REFERENCES code_ownership(id),
    created_by UUID REFERENCES users(id), -- Tracks which user created the rule
    rule_type VARCHAR(50) NOT NULL, -- 'BLOCK', 'REQUIRE_REVIEW', 'INFORM'
    guardrail_message TEXT NOT NULL
);
Note: For MySQL, use CHAR(36) for UUIDs and ensure LIKE BINARY is used for case-sensitive path matching.4. Python Library & Server StructureThe project is structured as a deployable Python package with a Command Line Interface (CLI) and a bundled frontend.SOLID Principles AppliedSingle Responsibility Principle (SRP): Connectors only handle search, Agent only handles logic, DB only handles storage, Routers only handle HTTP requests.Open/Closed Principle (OCP): New LLM providers or Search Connectors can be added by creating new classes that inherit from base interfaces.Liskov Substitution Principle (LSP): Any SemanticSearchProvider implementation can be swapped seamlessly.Interface Segregation Principle (ISP): Connectors implement specific interfaces (e.g., ISearchable) rather than a monolithic interface.Dependency Inversion Principle (DIP): The core agent depends on abstractions, not concrete implementations. Dependencies are injected at runtime via FastAPI's Depends().Folder Structurefeasibility_agent/
├── pyproject.toml             # Poetry/pip configuration
├── README.md
├── feasibility_agent/         # Main package
│   ├── __init__.py
│   ├── cli.py                 # Typer/Click CLI entry points
│   ├── server/                # FastAPI Application
│   │   ├── __init__.py
│   │   ├── app.py             # FastAPI instance & middleware
│   │   ├── dependencies.py    # DI container (DB sessions, Cache, Auth)
│   │   └── routers/           # API Endpoints
│   │       ├── chat.py        # WebSockets/SSE for agent loop
│   │       ├── users.py       # User management endpoints
│   │       └── config.py      # CRUD for dependency rules & code ownership
│   ├── ui/                    # Bundled Web UI (React/Vite build output)
│   │   ├── index.html
│   │   └── assets/
│   ├── agent/                 # LangGraph Implementation
│   │   ├── __init__.py
│   │   ├── graph.py           # LangGraph state machine definition
│   │   ├── nodes/             # Individual workflow steps
│   │   └── state.py           # TypedDict for agent memory
│   ├── connectors/            # BYOK Integrations (OCP/DIP)
│   │   ├── search/
│   │   └── llm/
│   ├── database/              # SQLAlchemy Layer
│   │   ├── models.py          # SQLAlchemy ORM models
│   │   └── repository.py      # Data access patterns
│   └── cache/                 # Distributed Caching
│       └── redis_manager.py
└── tests/
CLI Commands (Example)The CLI allows for easy deployment, while daily configuration is pushed to the Web UI.# Initialize the configuration file and database schema
feasibility-agent init

# Create the initial admin user to access the Web UI
feasibility-agent create-admin --username "admin" --email "admin@company.com"

# Start the server (serves both API and Web UI on port 8000)
feasibility-agent start --port 8000 --host 0.0.0.0
