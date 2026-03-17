import asyncio
import os
import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types
from dotenv import load_dotenv
import sys

load_dotenv()

app = Server("github-server")

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_USERNAME = os.getenv("GITHUB_USERNAME")

# base headers for every request to the GitHub API
HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28"
}


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    # exposing three read tools for now — file reader, commit lister, PR fetcher
    return [
        types.Tool(
            name="read_github_file",
            description="Fetch the contents of a file from a GitHub repository.",
            inputSchema={
                "type": "object",
                "properties": {
                    "repo": {
                        "type": "string",
                        "description": "Repository name in owner/repo format, e.g. 'myuser/myrepo'"
                    },
                    "path": {
                        "type": "string",
                        "description": "Path to the file inside the repo, e.g. 'src/main.py'"
                    },
                    "branch": {
                        "type": "string",
                        "description": "Branch to read from, defaults to main"
                    }
                },
                "required": ["repo", "path"]
            }
        ),
        types.Tool(
            name="list_github_commits",
            description="List recent commits on a branch of a GitHub repository.",
            inputSchema={
                "type": "object",
                "properties": {
                    "repo": {
                        "type": "string",
                        "description": "Repository name in owner/repo format"
                    },
                    "branch": {
                        "type": "string",
                        "description": "Branch to list commits from, defaults to main"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of commits to return, defaults to 10"
                    }
                },
                "required": ["repo"]
            }
        ),
        types.Tool(
            name="list_github_repos",
            description="List all repositories for the authenticated GitHub user.",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    async with httpx.AsyncClient() as client:

        if name == "list_github_repos":
            resp = await client.get(
                "https://api.github.com/user/repos?sort=updated&per_page=20",
                headers=HEADERS
            )
            if resp.status_code != 200:
                return [types.TextContent(type="text", text=f"GitHub API error: {resp.status_code} {resp.text}")]

            repos = resp.json()
            lines = [f"{r['full_name']} — {r['description'] or 'no description'}" for r in repos]
            return [types.TextContent(type="text", text="\n".join(lines))]

        elif name == "read_github_file":
            repo = arguments.get("repo")
            path = arguments.get("path")
            branch = arguments.get("branch", "main")

            resp = await client.get(
                f"https://api.github.com/repos/{repo}/contents/{path}?ref={branch}",
                headers=HEADERS
            )
            if resp.status_code != 200:
                return [types.TextContent(type="text", text=f"GitHub API error: {resp.status_code} {resp.text}")]

            data = resp.json()

            # github returns file content as base64, need to decode it
            import base64
            content = base64.b64decode(data["content"]).decode("utf-8")
            return [types.TextContent(type="text", text=content)]

        elif name == "list_github_commits":
            repo = arguments.get("repo")
            branch = arguments.get("branch", "main")
            limit = arguments.get("limit", 10)

            resp = await client.get(
                f"https://api.github.com/repos/{repo}/commits?sha={branch}&per_page={limit}",
                headers=HEADERS
            )
            if resp.status_code != 200:
                return [types.TextContent(type="text", text=f"GitHub API error: {resp.status_code} {resp.text}")]

            commits = resp.json()
            lines = []
            for c in commits:
                sha = c["sha"][:7]  # short SHA is enough for referencing
                message = c["commit"]["message"].split("\n")[0]  # just the first line
                author = c["commit"]["author"]["name"]
                date = c["commit"]["author"]["date"][:10]
                lines.append(f"{sha} | {date} | {author} | {message}")

            return [types.TextContent(type="text", text="\n".join(lines))]

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