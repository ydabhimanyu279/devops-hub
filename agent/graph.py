import asyncio
import sys
import os
from typing import TypedDict, Annotated
from contextlib import AsyncExitStack
from dotenv import load_dotenv
import anthropic
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import operator

load_dotenv()

# using haiku — cheapest claude model, fast, good enough for dev and demo
MODEL = "claude-haiku-4-5-20251001"


class AgentState(TypedDict):
    messages: Annotated[list, operator.add]
    tool_results: list
    final_answer: str
    pending_tool: str
    pending_input: dict


# ---- MCP server definitions ----

def get_server_configs() -> dict:
    # rag is handled directly in the main process now
    # only spinning up MCP subprocesses for github, jira, and filesystem
    return {
        "filesystem": StdioServerParameters(
            command=sys.executable,
            args=["mcp_servers/filesystem_server.py"]
        ),
        "github": StdioServerParameters(
            command=sys.executable,
            args=["mcp_servers/github_server.py"]
        ),
        "jira": StdioServerParameters(
            command=sys.executable,
            args=["mcp_servers/jira_server.py"]
        )
    }


async def get_tools_from_session(session: ClientSession, server_name: str) -> list:
    # converting MCP tool format to Anthropic's tool format and namespacing by server
    response = await session.list_tools()
    tools = []
    for tool in response.tools:
        tools.append({
            "name": f"{server_name}__{tool.name}",
            "description": tool.description,
            "input_schema": tool.inputSchema
        })
    return tools


async def call_tool_on_session(session: ClientSession, tool_name: str, tool_input: dict) -> str:
    result = await session.call_tool(tool_name, tool_input)
    return result.content[0].text if result.content else "No result returned."


# ---- Explicit router ----

def get_forced_tool(query: str) -> str | None:
    # keyword routing for high-confidence cases so I'm not relying on the model
    # to pick the right tool when there are 8 options — transparent and debuggable
    q = query.lower()
    rag_keywords = [
        "architecture", "adr", "compliance", "standard", "rule", "best practice",
        "oauth", "auth", "database access", "api design", "knowledge base"
    ]
    if any(k in q for k in rag_keywords):
        return "rag__query_rag_memory"
    return None


# write actions that require human approval before executing
WRITE_TOOLS = {"jira__create_jira_ticket"}


async def hitl_check_node(
    tool_name: str,
    tool_input: dict
) -> dict:
    # returning the pending action instead of executing it
    # the UI will render approval buttons and resume from here if approved
    return {
        "pending_approval": True,
        "tool_name": tool_name,
        "tool_input": tool_input
    }




async def input_node(state: AgentState) -> AgentState:
    return state


async def tool_decision_and_execution_node(
    state: AgentState,
    sessions: dict,
    tools: list
) -> AgentState:
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    system_prompt = """You are the Agentic DevOps Intelligence Hub.
You have MCP connections to GitHub, Jira, a local filesystem, and a RAG knowledge base of architecture decision records.

When answering questions:
- For incident analysis: check filesystem, GitHub commits, and Jira tickets
- For sprint summaries: pull GitHub commits and Jira ticket statuses
- Always cite exact commit SHAs, Jira ticket keys, and ADR numbers
- Be decisive — give root causes and recommendations, not just raw data"""

    tool_results = []
    user_query = state["messages"][-1]["content"]
    messages = [{"role": "user", "content": user_query}]

    # checking if this query should bypass the model and go straight to a specific tool
    forced_tool = get_forced_tool(user_query)
    if forced_tool:
        server_name, actual_tool_name = forced_tool.split("__", 1)
        print(f"  [router] forcing: {actual_tool_name} on {server_name} (direct)")

        # querying qdrant directly from the main process to avoid subprocess network issues
        result_text = query_qdrant_directly(user_query)
        tool_results.append({"server": "rag", "tool": "query_rag_memory", "result": result_text})

        # injecting the retrieved content so the model synthesizes from it
        synthesis_messages = [
            {"role": "user", "content": f"Here is the relevant content from the knowledge base:\n\n{result_text}\n\nUsing only this content, answer: {user_query}"}
        ]
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=system_prompt,
            messages=synthesis_messages
        )
        final_answer = response.content[0].text if response.content else ""
        return {**state, "messages": messages, "tool_results": tool_results, "final_answer": final_answer}

    # general agentic loop for queries not matched by the router
    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=system_prompt,
            tools=tools,
            messages=messages
        )

        if response.stop_reason == "end_turn":
            final_text = next((b.text for b in response.content if hasattr(b, "text")), "")
            return {**state, "messages": messages, "tool_results": tool_results, "final_answer": final_text}

        elif response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})
            tool_result_content = []

            for block in response.content:
                if block.type == "tool_use":
                    full_tool_name = block.name
                    tool_input = block.input or {}

                    if "__" in full_tool_name:
                        server_name, actual_tool_name = full_tool_name.split("__", 1)
                    else:
                        server_name, actual_tool_name = "filesystem", full_tool_name

                    # intercepting write actions before they execute
                    if full_tool_name in WRITE_TOOLS:
                        print(f"  [HITL] write action detected: {actual_tool_name} — returning for approval")
                        return {
                            **state,
                            "messages": messages,
                            "tool_results": tool_results,
                            "final_answer": "__HITL_PENDING__",
                            "pending_tool": full_tool_name,
                            "pending_input": tool_input
                        }

                    print(f"  [{server_name}] calling {actual_tool_name} with {tool_input}")

                    session = sessions.get(server_name)
                    result_text = await call_tool_on_session(session, actual_tool_name, tool_input) if session else f"No session for {server_name}"
                    tool_results.append({"server": server_name, "tool": actual_tool_name, "result": result_text})

                    tool_result_content.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_text
                    })

            messages.append({"role": "user", "content": tool_result_content})

        else:
            break

    return {**state, "messages": messages, "tool_results": tool_results, "final_answer": "Agent stopped unexpectedly."}


async def output_node(state: AgentState) -> AgentState:
    print("\n--- Agent Response ---")
    print(state["final_answer"])
    return state


# ---- Main entry point ----

async def run_agent(user_query: str):
    server_configs = get_server_configs()
    sessions = {}
    all_tools = []

    async with AsyncExitStack() as stack:
        for server_name, params in server_configs.items():
            read, write = await stack.enter_async_context(stdio_client(params))
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()

            tools = await get_tools_from_session(session, server_name)
            sessions[server_name] = session
            all_tools.extend(tools)
            print(f"connected to {server_name} — {len(tools)} tools")

        print(f"\ntotal tools available: {len(all_tools)}\n")

        initial_state: AgentState = {
            "messages": [{"role": "user", "content": user_query}],
            "tool_results": [],
            "final_answer": "",
            "pending_tool": "",
            "pending_input": {}
        }

        state = await input_node(initial_state)
        state = await tool_decision_and_execution_node(state, sessions, all_tools)
        state = await output_node(state)

        return state


if __name__ == "__main__":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    query = "What are our architecture rules around authentication and OAuth?"
    asyncio.run(run_agent(query))