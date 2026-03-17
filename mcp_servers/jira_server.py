import asyncio
import os
import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types
from dotenv import load_dotenv
import sys

load_dotenv()

app = Server("jira-server")

JIRA_BASE_URL = os.getenv("JIRA_BASE_URL")
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")
JIRA_PROJECT_KEY = os.getenv("JIRA_PROJECT_KEY")

# jira uses HTTP basic auth — email + api token encoded together
AUTH = (JIRA_EMAIL, JIRA_API_TOKEN)
HEADERS = {"Accept": "application/json", "Content-Type": "application/json"}


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    # two tools for now: search existing tickets, create a new one
    # create_ticket will get a HITL gate added in Phase 4
    return [
        types.Tool(
            name="search_jira_tickets",
            description="Search for Jira tickets in the project by keyword or status.",
            inputSchema={
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "Word or phrase to search for in ticket summaries"
                    },
                    "status": {
                        "type": "string",
                        "description": "Filter by status: 'To Do', 'In Progress', 'Done'"
                    }
                }
            }
        ),
        types.Tool(
            name="create_jira_ticket",
            description="Create a new Jira ticket. Requires user approval before calling.",
            inputSchema={
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Title of the ticket"
                    },
                    "description": {
                        "type": "string",
                        "description": "Detailed description of the issue"
                    },
                    "issue_type": {
                        "type": "string",
                        "description": "Type of issue: 'Bug', 'Task', or 'Story'"
                    }
                },
                "required": ["summary", "description", "issue_type"]
            }
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    async with httpx.AsyncClient() as client:

        if name == "search_jira_tickets":
            keyword = arguments.get("keyword", "")
            status = arguments.get("status", "")

            # building a JQL query depending on what filters were passed in
            jql_parts = [f"project = {JIRA_PROJECT_KEY}"]
            if keyword:
                jql_parts.append(f'summary ~ "{keyword}"')
            if status:
                jql_parts.append(f'status = "{status}"')

            jql = " AND ".join(jql_parts) + " ORDER BY created DESC"

            resp = await client.get(
                f"{JIRA_BASE_URL}/rest/api/3/search/jql",
                params={"jql": jql, "maxResults": 20, "fields": "summary,status,assignee,description"},
                headers=HEADERS,
                auth=AUTH
            )

            if resp.status_code != 200:
                return [types.TextContent(type="text", text=f"Jira API error: {resp.status_code} {resp.text}")]

            issues = resp.json().get("issues", [])
            if not issues:
                return [types.TextContent(type="text", text="No tickets found matching that query.")]

            lines = []
            for issue in issues:
                key = issue["key"]
                summary = issue["fields"]["summary"]
                status = issue["fields"]["status"]["name"]
                assignee = issue["fields"].get("assignee")
                assignee_name = assignee["displayName"] if assignee else "Unassigned"
                lines.append(f"{key} | {status} | {assignee_name} | {summary}")

            return [types.TextContent(type="text", text="\n".join(lines))]

        elif name == "create_jira_ticket":
            summary = arguments.get("summary")
            description = arguments.get("description")
            issue_type = arguments.get("issue_type", "Task")

            # jira's v3 API requires description in Atlassian Document Format (ADF), not plain text
            payload = {
                "fields": {
                    "project": {"key": JIRA_PROJECT_KEY},
                    "summary": summary,
                    "description": {
                        "type": "doc",
                        "version": 1,
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": description}]
                            }
                        ]
                    },
                    "issuetype": {"name": issue_type}
                }
            }

            resp = await client.post(
                f"{JIRA_BASE_URL}/rest/api/3/issue",
                json=payload,
                headers=HEADERS,
                auth=AUTH
            )

            if resp.status_code not in (200, 201):
                return [types.TextContent(type="text", text=f"Jira API error: {resp.status_code} {resp.text}")]

            ticket_key = resp.json().get("key")
            return [types.TextContent(type="text", text=f"Ticket created: {ticket_key} — {summary}")]

        else:
            return [types.TextContent(type="text", text=f"Unknown tool: {name}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())