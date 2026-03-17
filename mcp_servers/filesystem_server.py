import asyncio
import os
import sys
from pathlib import Path
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

# naming the server so it's identifiable when the agent connects to it
app = Server("filesystem-server")

# locking the agent to this folder so it can't go reading things it shouldn't
WORKSPACE_DIR = Path(__file__).parent.parent / "workspace"


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    # this is how the agent knows what tools exist on this server
    # I'm exposing two for now: read a file, or list what's there
    return [
        types.Tool(
            name="read_file",
            description="Read the contents of a file from the workspace directory.",
            inputSchema={
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "The name of the file to read (e.g. 'notes.txt')"
                    }
                },
                "required": ["filename"]
            }
        ),
        types.Tool(
            name="list_files",
            description="List all files available in the workspace directory.",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    # agent routes here whenever it decides to use one of my tools

    if name == "list_files":
        if not WORKSPACE_DIR.exists():
            return [types.TextContent(
                type="text",
                text="Workspace directory does not exist."
            )]
        files = [f.name for f in WORKSPACE_DIR.iterdir() if f.is_file()]
        file_list = "\n".join(files) if files else "No files found."
        return [types.TextContent(type="text", text=file_list)]

    elif name == "read_file":
        filename = arguments.get("filename")
        file_path = WORKSPACE_DIR / filename

        # making sure the agent can't climb out of the workspace with a sneaky path like ../../secrets
        if not file_path.resolve().is_relative_to(WORKSPACE_DIR.resolve()):
            return [types.TextContent(
                type="text",
                text="Access denied: cannot read files outside workspace."
            )]

        if not file_path.exists():
            return [types.TextContent(
                type="text",
                text=f"File '{filename}' not found in workspace."
            )]

        content = file_path.read_text(encoding="utf-8")
        return [types.TextContent(type="text", text=content)]

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
    # Windows needs this or asyncio throws a fit at shutdown
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())