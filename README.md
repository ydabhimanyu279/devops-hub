# Agentic DevOps Intelligence Hub

A context-aware AI agent that connects to GitHub, Jira, and a RAG knowledge base via the Model Context Protocol (MCP) to automate cross-tool DevOps workflows. Built with Claude as the reasoning engine, Qdrant for vector memory, and a Human-in-the-Loop approval gate for all write actions.

**Live Demo:** https://devops-app-jge7tcshbtlyjakd2f3fiq.streamlit.app

---

## What It Does

Instead of manually switching between GitHub, Jira, and internal documentation to investigate an incident or check architecture compliance, you ask the agent a single question and it pulls everything together automatically.

**Example queries you can try:**

- "There's an OOM crash in the payment service — what happened and does it violate any architecture rules?"
- "List my GitHub repos and summarize open Jira tickets"
- "What are our architecture rules around authentication and OAuth?"
- "Does our codebase comply with ADR-001?"
- "Create a Jira ticket to track the post-incident review" — triggers the HITL approval gate

---

## Architecture

```
User (Streamlit UI)
        ↓
Agent loop (LangGraph + Claude)
        ↓
┌──────────────────────────────────────────────────┐
│  GitHub MCP  │  Jira MCP  │  Filesystem MCP  │  Qdrant RAG  │
└──────────────────────────────────────────────────┘
```

**Agent node flow:**

```
input_node
    ↓
keyword_router         — routes RAG queries directly, bypassing model tool selection
    ↓
tool_decision_node     — Claude decides which MCP tools to call
    ↓
tool_execution_node    — calls MCP tools
    ↓
hitl_check_node        — pauses on write actions and waits for human approval
    ↓
synthesis_node         — Claude synthesizes all tool results into a final answer
    ↓
output_node
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| LLM | Claude (Anthropic) |
| Agent orchestration | LangGraph |
| Tool protocol | MCP (Model Context Protocol) |
| Vector database | Qdrant Cloud |
| Embeddings | fastembed (BAAI/bge-small-en-v1.5) |
| Integrations | GitHub REST API, Jira REST API v3 |
| Frontend | Streamlit |
| Language | Python 3.11+ |

---

## MCP Tools

| Tool | Type | Description |
|---|---|---|
| `list_files` | READ | Lists files in the local workspace |
| `read_file` | READ | Reads a file from the local workspace |
| `list_github_repos` | READ | Lists repositories for the authenticated user |
| `list_github_commits` | READ | Lists recent commits on a branch with SHAs |
| `read_github_file` | READ | Fetches a file from a GitHub repo by path |
| `search_jira_tickets` | READ | Searches Jira by keyword or status using JQL |
| `create_jira_ticket` | WRITE (HITL) | Creates a Jira ticket — requires human approval |
| `query_rag_memory` | READ | Semantic search over ADRs in Qdrant |

---

## Project Structure

```
devops-hub/
├── app.py                        # Streamlit chat UI with HITL approval panel
├── agent/
│   └── graph.py                  # LangGraph agent loop and node definitions
├── mcp_servers/
│   ├── filesystem_server.py      # Local file MCP server
│   ├── github_server.py          # GitHub MCP server
│   ├── jira_server.py            # Jira MCP server
│   └── rag_server.py             # Qdrant RAG MCP server
├── scripts/
│   └── load_adrs.py              # Loads ADRs into Qdrant Cloud
├── workspace/
│   ├── adrs/
│   │   ├── adr-001-auth.md       # OAuth 2.1 and JWT standard
│   │   ├── adr-002-api.md        # REST API versioning standard
│   │   └── adr-003-database.md   # Database access standard
│   └── incident_report.txt
├── .env.example
├── requirements.txt
└── README.md
```

---

## Setup

### 1. Clone and install

```bash
git clone https://github.com/ydabhimanyu279/devops-hub.git
cd devops-hub
python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # Mac/Linux
pip install -r requirements.txt
```

### 2. Configure environment variables

```bash
cp .env.example .env
```

| Variable | Where to get it |
|---|---|
| `ANTHROPIC_API_KEY` | console.anthropic.com |
| `GITHUB_TOKEN` | GitHub → Settings → Developer settings → Tokens (classic) |
| `GITHUB_USERNAME` | Your GitHub username |
| `JIRA_BASE_URL` | Your Atlassian site URL e.g. https://yoursite.atlassian.net |
| `JIRA_EMAIL` | Your Atlassian account email |
| `JIRA_API_TOKEN` | id.atlassian.com → Security → API tokens |
| `JIRA_PROJECT_KEY` | Your Jira project key e.g. SCRUM |
| `QDRANT_URL` | cloud.qdrant.io → your cluster URL |
| `QDRANT_API_KEY` | cloud.qdrant.io → your cluster API key |

### 3. Load the knowledge base

```bash
python scripts/load_adrs.py
```

### 4. Run locally

```bash
streamlit run app.py
```

---

## Key Design Decisions

**Why MCP instead of direct API calls?**
MCP gives each integration a standard interface so the agent can discover and call tools dynamically. Adding a new data source means writing a new MCP server — not modifying the agent core.

**Why explicit keyword routing for RAG queries?**
With 8 tools available, smaller models route inconsistently under load. Keyword routing for high-confidence cases (architecture and compliance queries) is transparent, debuggable, and doesn't depend on prompt sensitivity.

**Why HITL for write actions?**
AI agents making write actions without human oversight is a compliance and audit risk in enterprise environments. The HITL gate freezes the agent before any write action and requires explicit approval before execution.

**Why Qdrant for the RAG layer?**
Qdrant Cloud has a free hosted tier, supports fast approximate nearest neighbor search via `query_points`, and integrates with fastembed for local embeddings without needing torch or GPU dependencies.

---

## Architecture Decision Records

The agent's RAG memory is seeded with three ADRs that represent real organizational standards:

- **ADR-001** — Authentication standard: OAuth 2.1 with PKCE mandatory, JWT tokens only, 1-hour expiry, refresh token rotation
- **ADR-002** — API design standard: REST over HTTPS, versioned endpoints (/v1/, /v2/), standard envelope response format
- **ADR-003** — Database access standard: no cross-service DB access, ORM only, no hardcoded credentials, environment variable injection required

---

