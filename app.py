import asyncio
import sys
import streamlit as st
from agent.graph import run_agent

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def run_agent_sync(query: str) -> dict:
    # each query gets its own event loop to avoid conflicts between runs
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(run_agent(query))
    finally:
        loop.close()


# ---- page config ----

st.set_page_config(
    page_title="DevOps Intelligence Hub",
    layout="wide"
)

st.title("Agentic DevOps Intelligence Hub")
st.caption("Connected to GitHub, Jira, and a RAG knowledge base of architecture decision records.")

# ---- sidebar ----

with st.sidebar:
    st.header("Connected Tools")
    st.markdown("""
    - **Filesystem** — local incident reports
    - **GitHub** — repos and commits
    - **Jira** — tickets and sprint status
    - **RAG Memory** — architecture decision records
    """)
    st.divider()
    st.header("Example Queries")
    example_queries = [
        "What are our architecture rules around authentication and OAuth?",
        "List my GitHub repos and search Jira for open tickets",
        "Search Jira for auth-related tickets and find related GitHub repos",
        "What does our API design standard say about versioning?",
        "Read the incident report and summarize what happened",
        "Create a Jira ticket: API gateway is returning 503 errors on /v1/payments",
    ]
    for q in example_queries:
        if st.button(q, use_container_width=True):
            st.session_state["pending_query"] = q

# ---- session state init ----

if "messages" not in st.session_state:
    st.session_state.messages = []

if "tool_calls" not in st.session_state:
    st.session_state.tool_calls = []

if "pending_approval" not in st.session_state:
    st.session_state.pending_approval = None


# ---- helper: process a query and handle HITL ----

def process_query(query: str):
    st.session_state.messages.append({"role": "user", "content": query})

    with st.chat_message("user"):
        st.markdown(query)

    with st.chat_message("assistant"):
        with st.spinner("Agent is thinking..."):
            try:
                result = run_agent_sync(query)
                answer = result["final_answer"]
                tool_calls = result.get("tool_results", [])

                if answer == "__HITL_PENDING__":
                    # storing the pending action so the approval UI can render below
                    st.session_state.pending_approval = {
                        "tool_name": result.get("pending_tool"),
                        "tool_input": result.get("pending_input")
                    }
                    answer = "I need your approval before creating this Jira ticket."

            except Exception as e:
                answer = f"Error: {str(e)}"
                tool_calls = []

        st.markdown(answer)

        if tool_calls:
            with st.expander(f"Tool calls ({len(tool_calls)})"):
                for tc in tool_calls:
                    st.code(f"[{tc['server']}] {tc['tool']}\n{tc['result'][:300]}...")

    st.session_state.messages.append({"role": "assistant", "content": answer})
    st.session_state.tool_calls.extend(tool_calls)


# ---- render past messages ----

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ---- HITL approval panel ----
# rendering this after messages so it appears at the bottom of the conversation

if st.session_state.pending_approval:
    pending = st.session_state.pending_approval

    st.warning("Approval required before this write action executes.")
    with st.expander("Review ticket payload", expanded=True):
        st.json(pending["tool_input"])

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Approve and create ticket", type="primary", use_container_width=True):
            with st.spinner("Creating ticket..."):
                try:
                    # calling the jira server directly to execute the approved action
                    import asyncio
                    from mcp import ClientSession, StdioServerParameters
                    from mcp.client.stdio import stdio_client
                    import sys

                    async def execute_approved():
                        params = StdioServerParameters(
                            command=sys.executable,
                            args=["mcp_servers/jira_server.py"]
                        )
                        async with stdio_client(params) as (read, write):
                            async with ClientSession(read, write) as session:
                                await session.initialize()
                                result = await session.call_tool(
                                    "create_jira_ticket",
                                    pending["tool_input"]
                                )
                                return result.content[0].text if result.content else "Ticket created."

                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    answer = loop.run_until_complete(execute_approved())
                    loop.close()

                except Exception as e:
                    answer = f"Error creating ticket: {str(e)}"

            st.session_state.messages.append({"role": "assistant", "content": answer})
            st.session_state.pending_approval = None
            st.rerun()

    with col2:
        if st.button("Reject", use_container_width=True):
            st.session_state.messages.append({
                "role": "assistant",
                "content": "Action rejected. No Jira ticket was created."
            })
            st.session_state.pending_approval = None
            st.rerun()

# ---- sidebar example query handler ----

if "pending_query" in st.session_state:
    query = st.session_state.pop("pending_query")
    process_query(query)
    st.rerun()

# ---- main chat input ----

if query := st.chat_input("Ask about your repos, tickets, incidents, or architecture rules..."):
    process_query(query)
    st.rerun()