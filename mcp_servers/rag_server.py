import asyncio
import os
from dotenv import load_dotenv
from qdrant_client import QdrantClient
from fastembed import TextEmbedding
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

load_dotenv()

app = Server("rag-server")

# connecting to qdrant cloud instead of local docker
client = QdrantClient(
    url=os.getenv("QDRANT_URL"),
    api_key=os.getenv("QDRANT_API_KEY")
)

# loading the same model used during ingestion so the vector space matches
# fastembed caches the model locally after the first download so this is fast
model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")

COLLECTION_NAME = "adrs"


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="query_rag_memory",
            description=(
                "Semantic search over the architecture decision records (ADRs) and runbooks. "
                "Use this whenever a question involves architecture rules, compliance, or best practices."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The question or topic to search for in the knowledge base"
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of documents to return, defaults to 3"
                    }
                },
                "required": ["query"]
            }
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "query_rag_memory":
        query = arguments.get("query", "")
        top_k = arguments.get("top_k", 3)

        # embedding the query using the same model so it lands in the same vector space
        query_vector = list(model.embed([query]))[0].tolist()

        results = client.query_points(
            collection_name=COLLECTION_NAME,
            query=query_vector,
            limit=top_k,
            with_payload=True
        ).points

        if not results:
            return [types.TextContent(type="text", text="No relevant documents found in the knowledge base.")]

        # formatting each result with its score so the agent knows how confident to be
        output_parts = []
        for i, result in enumerate(results):
            filename = result.payload.get("filename", "unknown")
            content = result.payload.get("content", "")
            score = round(result.score, 3)
            output_parts.append(f"[{i+1}] {filename} (relevance: {score})\n\n{content}")

        return [types.TextContent(type="text", text="\n\n---\n\n".join(output_parts))]

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
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())