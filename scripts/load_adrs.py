import os
from pathlib import Path
from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from fastembed import TextEmbedding

load_dotenv()

# connecting to qdrant cloud so the data persists for the live demo
client = QdrantClient(
    url=os.getenv("QDRANT_URL"),
    api_key=os.getenv("QDRANT_API_KEY")
)

# fastembed runs locally, no torch needed, and works fine on Python 3.13
# BAAI/bge-small-en-v1.5 produces 384-dim vectors, same size as MiniLM
model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")

COLLECTION_NAME = "adrs"
ADR_DIR = Path("workspace/adrs")

def setup_collection():
    # creating the collection if it doesn't already exist
    # 384 is the vector size that all-MiniLM-L6-v2 produces
    existing = [c.name for c in client.get_collections().collections]
    if COLLECTION_NAME in existing:
        print(f"collection '{COLLECTION_NAME}' already exists, deleting and recreating")
        client.delete_collection(COLLECTION_NAME)

    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(size=384, distance=Distance.COSINE)
    )
    print(f"created collection '{COLLECTION_NAME}'")


def load_adrs():
    adr_files = list(ADR_DIR.glob("*.md"))
    if not adr_files:
        print("no ADR files found in workspace/adrs")
        return

    points = []
    for i, filepath in enumerate(adr_files):
        content = filepath.read_text(encoding="utf-8")
        # embedding the full document text into a vector
        # fastembed returns a generator so I need to pull the first result out
        vector = list(model.embed([content]))[0].tolist()

        points.append(PointStruct(
            id=i,
            vector=vector,
            payload={
                "filename": filepath.name,
                "content": content,
                "title": filepath.stem
            }
        ))
        print(f"embedded {filepath.name}")

    client.upsert(collection_name=COLLECTION_NAME, points=points)
    print(f"\nloaded {len(points)} ADRs into qdrant")


if __name__ == "__main__":
    setup_collection()
    load_adrs()
    print("done — ADRs are ready to query")