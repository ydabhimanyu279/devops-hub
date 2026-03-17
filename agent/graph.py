import asyncio
import sys
import os
import base64
import httpx
from typing import TypedDict, Annotated
from contextlib import AsyncExitStack
from dotenv import load_dotenv
import anthropic
from qdrant_client import QdrantClient
from fastembed import TextEmbedding
import operator

load_dotenv()

MODEL = "claude-haiku-4-5-20251001"

# ---- direct API clients (no MCP subprocesses) ----
# running everything in the main process so Streamlit Cloud's sandbox
# doesn't kill subprocess connections

GITHUB_HEADERS = {
    "Authorization": f"Bearer {os.getenv('GITHUB_TOKEN')}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28"
}

JIRA_BASE_URL = os.getenv("JIRA_BASE_URL")
JIRA_AUTH = (os.getenv("JIRA_EMAIL"), os.getenv("JIRA_API_TOKEN"))
JIRA_PROJECT_KEY = os.getenv("JIRA_PROJECT_KEY")
JIRA_HEADERS = {"Accept": "application/json", "Content-Type": "application/json"}

_qdrant_client = None
_embed_model = None


def get_qdrant_client():
    global _qdrant_client
    if _qdrant_client is None:
        _qdrant_client = QdrantClient(
            url=os.getenv("QDRANT_URL"),
            api_key=os.getenv("QDRANT_API_KEY")
        )
    return _qdrant_client


def get_embed_model():
    global _embed_model
    if _embed_model is None:
        _embed_model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
    return _embed_model


# ---- tool implementations ----

def query_rag(query: str) -> str:
    client = get_qdrant_client()
    model = get_embed_model()
    query_vector = list(model.embed([query]))[0].tolist()
    results = client.query_points(
        collection_name="adrs",
        query=query_vector,
        limit=3,
        with_payload=True
    ).points
    if not results:
        return "No relevant documents found."
    parts = []
    for i, r in enumerate(results):
        parts.append(f"[{i+1}] {r.payload.get('filename')} (score: {round(r.score, 3)})\n\n{r.payload.get('content')}")
    return "\n\n---\n\n".join(parts)


async def list_github_repos() -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://api.github.com/user/repos?sort=updated&per_page=20",
            headers=GITHUB_HEADERS
        )
        if resp.status_code != 200:
            return f"GitHub error: {resp.status_code}"
        repos = resp.json()
        lines = [f"{r['full_name']} — {r['description'] or 'no description'}" for r in repos]
        return "\n".join(lines)


async def list_github_commits(repo: str, branch: str = "main", limit: int = 10) -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://api.github.com/repos/{repo}/commits?sha={branch}&per_page={limit}",
            headers=GITHUB_HEADERS
        )
        if resp.status_code != 200:
            return f"GitHub error: {resp.status_code}"
        commits = resp.json()
        lines = []
        for c in commits:
            sha = c["sha"][:7]
            msg = c["commit"]["message"].split("\n")[0]
            author = c["commit"]["author"]["name"]
            date = c["commit"]["author"]["date"][:10]
            lines.append(f"{sha} | {date} | {author} | {msg}")
        return "\n".join(lines)


async def search_jira_tickets(keyword: str = "", status: str = "") -> str:
    jql_parts = [f"project = {JIRA_PROJECT_KEY}"]
    if keyword:
        jql_parts.append(f'summary ~ "{keyword}"')
    if status:
        jql_parts.append(f'status = "{status}"')
    jql = " AND ".join(jql_parts) + " ORDER BY created DESC"

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{JIRA_BASE_URL}/rest/api/3/search/jql",
            params={"jql": jql, "maxResults": 20, "fields": "summary,status,assignee"},
            headers=JIRA_HEADERS,
            auth=JIRA_AUTH
        )
        if resp.status_code != 200:
            return f"Jira error: {resp.status_code}"
        issues = resp.json().get("issues", [])
        if not issues:
            return "No tickets found."
        lines = []
        for issue in issues:
            key = issue["key"]
            summary = issue["fields"]["summary"]
            status = issue["fields"]["status"]["name"]
            assignee = issue["fields"].get("assignee")
            name = assignee["displayName"] if assignee else "Unassigned"
            lines.append(f"{key} | {status} | {name} | {summary}")
        return "\n".join(lines)


async def create_jira_ticket(summary: str, description: str, issue_type: str = "Task") -> str:
    payload = {
        "fields": {
            "project": {"key": JIRA_PROJECT_KEY},
            "summary": summary,
            "description": {
                "type": "doc",
                "version": 1,
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": description}]}]
            },
            "issuetype": {"name": issue_type}
        }
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{JIRA_BASE_URL}/rest/api/3/issue",
            json=payload,
            headers=JIRA_HEADERS,
            auth=JIRA_AUTH
        )
        if resp.status_code not in (200, 201):
            return f"Jira error: {resp.status_code} {resp.text}"
        return f"Ticket created: {resp.json().get('key')} — {summary}"


def read_workspace_file(filename: str) -> str:
    from pathlib import Path
    workspace = Path("workspace")
    filepath = workspace / filename
    if not filepath.exists():
        return f"File '{filename}' not found."
    return filepath.read_text(encoding="utf-8")


def list_workspace_files() -> str:
    from pathlib import Path
    workspace = Path("workspace")
    if not workspace.exists():
        return "Workspace directory not found."
    files = [f.name for f in workspace.iterdir() if f.is_file()]
    return "\n".join(files) if files else "No files found."


# ---- tool definitions for Claude ----

TOOLS = [
    {
        "name": "list_github_repos",
        "description": "List all GitHub repositories for the authenticated user.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "list_github_commits",
        "description": "List recent commits on a GitHub repo branch.",
        "input_schema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "owner/repo format"},
                "branch": {"type": "string", "description": "branch name, defaults to main"},
                "limit": {"type": "integer", "description": "number of commits"}
            },
            "required": ["repo"]
        }
    },
    {
        "name": "search_jira_tickets",
        "description": "Search Jira tickets by keyword or status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "search term"},
                "status": {"type": "string", "description": "To Do, In Progress, or Done"}
            }
        }
    },
    {
        "name": "create_jira_ticket",
        "description": "Create a Jira ticket. Requires human approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "description": {"type": "string"},
                "issue_type": {"type": "string", "description": "Bug, Task, or Story"}
            },
            "required": ["summary", "description", "issue_type"]
        }
    },
    {
        "name": "list_workspace_files",
        "description": "List files in the local workspace directory.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "read_workspace_file",
        "description": "Read a file from the local workspace.",
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {"type": "string"}
            },
            "required": ["filename"]
        }
    },
    {
        "name": "query_rag_memory",
        "description": "Semantic search over architecture decision records.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"}
            },
            "required": ["query"]
        }
    }
]

WRITE_TOOLS = {"create_jira_ticket"}

# ---- state ----

class AgentState(TypedDict):
    messages: Annotated[list, operator.add]
    tool_results: list
    final_answer: str
    pending_tool: str
    pending_input: dict


# ---- router ----

def get_forced_tool(query: str) -> str | None:
    q = query.lower()
    rag_keywords = [
        "architecture", "adr", "compliance", "standard", "rule", "best practice",
        "oauth", "auth", "database access", "api design", "knowledge base"
    ]
    if any(k in q for k in rag_keywords):
        return "query_rag_memory"
    return None


# ---- tool executor ----

async def execute_tool(tool_name: str, tool_input: dict) -> str:
    if tool_name == "list_github_repos":
        return await list_github_repos()
    elif tool_name == "list_github_commits":
        return await list_github_commits(**tool_input)
    elif tool_name == "search_jira_tickets":
        return await search_jira_tickets(**tool_input)
    elif tool_name == "create_jira_ticket":
        return await create_jira_ticket(**tool_input)
    elif tool_name == "list_workspace_files":
        return list_workspace_files()
    elif tool_name == "read_workspace_file":
        return read_workspace_file(**tool_input)
    elif tool_name == "query_rag_memory":
        return query_rag(tool_input.get("query", ""))
    return f"Unknown tool: {tool_name}"


# ---- agent ----

async def run_agent(user_query: str) -> dict:
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    system_prompt = """You are the Agentic DevOps Intelligence Hub.
You have tools to query GitHub, Jira, a local filesystem, and a RAG knowledge base of architecture decision records.

When answering questions:
- For incident analysis: check workspace files, GitHub commits, and Jira tickets
- For sprint summaries: pull GitHub commits and Jira ticket statuses
- Always cite exact commit SHAs, Jira ticket keys, and ADR numbers
- Be decisive — give root causes and recommendations, not just raw data"""

    tool_results = []
    messages = [{"role": "user", "content": user_query}]

    # direct RAG for architecture queries
    forced_tool = get_forced_tool(user_query)
    if forced_tool:
        print(f"  [router] forcing: {forced_tool}")
        result_text = query_rag(user_query)
        tool_results.append({"server": "rag", "tool": forced_tool, "result": result_text})

        synthesis_messages = [{
            "role": "user",
            "content": f"Here is the relevant content from the knowledge base:\n\n{result_text}\n\nUsing only this content, answer: {user_query}"
        }]
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=system_prompt,
            messages=synthesis_messages
        )
        return {
            "messages": messages,
            "tool_results": tool_results,
            "final_answer": response.content[0].text,
            "pending_tool": "",
            "pending_input": {}
        }

    # general agentic loop
    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=system_prompt,
            tools=TOOLS,
            messages=messages
        )

        if response.stop_reason == "end_turn":
            final_text = next((b.text for b in response.content if hasattr(b, "text")), "")
            return {"messages": messages, "tool_results": tool_results, "final_answer": final_text, "pending_tool": "", "pending_input": {}}

        elif response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})
            tool_result_content = []

            for block in response.content:
                if block.type == "tool_use":
                    tool_name = block.name
                    tool_input = block.input or {}

                    if tool_name in WRITE_TOOLS:
                        print(f"  [HITL] write action detected: {tool_name}")
                        return {
                            "messages": messages,
                            "tool_results": tool_results,
                            "final_answer": "__HITL_PENDING__",
                            "pending_tool": tool_name,
                            "pending_input": tool_input
                        }

                    print(f"  calling {tool_name} with {tool_input}")
                    result_text = await execute_tool(tool_name, tool_input)
                    tool_results.append({"server": "direct", "tool": tool_name, "result": result_text})
                    tool_result_content.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_text
                    })

            messages.append({"role": "user", "content": tool_result_content})

        else:
            break

    return {"messages": messages, "tool_results": tool_results, "final_answer": "Agent stopped unexpectedly.", "pending_tool": "", "pending_input": {}}