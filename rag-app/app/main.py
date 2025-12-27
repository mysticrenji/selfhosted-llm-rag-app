"""RAG API with Docling, LangChain, and Meilisearch."""
import logging
import os
import shutil
import uuid
from pathlib import Path
from typing import Any, Optional

import meilisearch
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from langchain_chroma import Chroma
from langchain_classic.chains import create_retrieval_chain
from langchain_classic.chains.combine_documents import create_stuff_documents_chain
from langchain_classic.retrievers.ensemble import EnsembleRetriever
from langchain_community.vectorstores.utils import filter_complex_metadata
from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.retrievers import BaseRetriever

# LangChain
from langchain_docling import DoclingLoader
from langchain_openai import ChatOpenAI
from langchain_text_splitters import RecursiveCharacterTextSplitter

# Langfuse for observability
from langfuse.callback import CallbackHandler
from pydantic import BaseModel

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="RAG API", description="Self-hosted RAG with Meilisearch + Chroma Hybrid Search")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration
CHROMA_HOST = os.getenv("CHROMA_HOST", "chromadb.llm-stack.svc.cluster.local")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000"))
MEILI_HOST = os.getenv("MEILI_HOST", "http://meilisearch.llm-stack.svc.cluster.local:7700")
MEILI_MASTER_KEY = os.getenv("MEILI_MASTER_KEY", "masterKey")
LLM_API_BASE = os.getenv("LLM_API_BASE", "http://litellm.llm-stack.svc.cluster.local:4000")
LLM_API_KEY = os.getenv("LLM_API_KEY", "sk-admin-secret-key")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "mxbai-embed-large")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-3.5-turbo")
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", str(50 * 1024 * 1024)))  # 50MB default

# Langfuse Configuration
LANGFUSE_HOST = os.getenv("LANGFUSE_HOST", "http://langfuse.llm-stack.svc.cluster.local:3000")
LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY", "")
LANGFUSE_ENABLED = os.getenv("LANGFUSE_ENABLED", "true").lower() == "true"


# --- CUSTOM MEILISEARCH RETRIEVER ---
class MeilisearchRetriever(BaseRetriever):
    client: Any
    index_name: str
    k: int = 5

    def _get_relevant_documents(self, query: str, *, run_manager: CallbackManagerForRetrieverRun) -> list[Document]:
        index = self.client.index(self.index_name)
        search_results = index.search(query, {"limit": self.k})

        docs = []
        for hit in search_results["hits"]:
            # Meilisearch stores content and separate metadata fields
            # We reconstruct the Document object
            content = hit.get("text", "")
            # Extract metadata (everything except text/id/vectors)
            metadata = {k: v for k, v in hit.items() if k not in ["text", "id", "_vectors"]}
            docs.append(Document(page_content=content, metadata=metadata))
        return docs


# --- INITIALIZATION ---

logger.info(f"Connecting to LiteLLM at {LLM_API_BASE}")

# Initialize Langfuse
langfuse_handler: Optional[CallbackHandler] = None
if LANGFUSE_ENABLED and LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY:
    try:
        langfuse_handler = CallbackHandler(
            public_key=LANGFUSE_PUBLIC_KEY,
            secret_key=LANGFUSE_SECRET_KEY,
            host=LANGFUSE_HOST,
        )
        logger.info(f"Langfuse observability enabled at {LANGFUSE_HOST}")
    except Exception as e:
        logger.warning(f"Failed to initialize Langfuse: {e}. Continuing without observability.")
else:
    logger.info("Langfuse observability disabled")

# Custom Embeddings class for Ollama/LiteLLM compatibility (no encoding_format)

import requests
from langchain_core.embeddings import Embeddings


class LiteLLMEmbeddings(Embeddings):
    """Custom embeddings that call LiteLLM without encoding_format parameter."""

    def __init__(self, api_base: str, api_key: str, model: str, batch_size: int = 10):
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.batch_size = batch_size

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of documents in batches."""
        all_embeddings = []

        # Filter and log overly long texts
        processed_texts = []
        for idx, text in enumerate(texts):
            # Rough token estimate: ~4 chars per token
            # nomic-embed-text via Ollama has 512 token limit, be VERY conservative
            max_chars = 800  # ~200 tokens, well under 512 limit

            if len(text) > max_chars:
                estimated_tokens = len(text) // 4
                logger.warning(
                    f"Chunk {idx} too large (~{estimated_tokens} tokens, {len(text)} chars), truncating to {max_chars} chars..."
                )
                text = text[:max_chars]
            processed_texts.append(text)

        # Process in batches to avoid overwhelming the API
        for i in range(0, len(processed_texts), self.batch_size):
            batch = processed_texts[i : i + self.batch_size]

            try:
                # Log what we're sending for debugging
                max_len = max(len(t) for t in batch) if batch else 0
                logger.info(f"Sending batch of {len(batch)} texts, max length: {max_len} chars (~{max_len//4} tokens)")

                response = requests.post(
                    f"{self.api_base}/embeddings",
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json={"model": self.model, "input": batch},
                    timeout=60,
                )
                response.raise_for_status()
                data = response.json()
                batch_embeddings = [item["embedding"] for item in data["data"]]
                all_embeddings.extend(batch_embeddings)

                logger.info(f"Embedded batch {i//self.batch_size + 1}/{(len(processed_texts)-1)//self.batch_size + 1}")

            except requests.exceptions.HTTPError as e:
                error_text = e.response.text if e.response else str(e)
                logger.error(f"Embedding API error: {error_text}")
                logger.error(f"Failed batch had {len(batch)} texts with lengths: {[len(t) for t in batch]}")
                raise HTTPException(status_code=500, detail=f"Embedding failed: {error_text}")

        return all_embeddings

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query."""
        return self.embed_documents([text])[0]


embeddings = LiteLLMEmbeddings(
    api_base=LLM_API_BASE,
    api_key=LLM_API_KEY,
    model=EMBEDDING_MODEL,
    batch_size=1,  # Process one at a time to avoid any batching issues
)

llm = ChatOpenAI(openai_api_base=LLM_API_BASE, openai_api_key=LLM_API_KEY, model_name=LLM_MODEL, temperature=0.7)

# Initialize Stores
vector_store: Optional[Chroma] = None
meili_client: Optional[meilisearch.Client] = None

try:
    import chromadb

    chroma_client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
    vector_store = Chroma(
        client=chroma_client,
        collection_name="rag_documents",
        embedding_function=embeddings,
    )
    logger.info("Connected to ChromaDB")
except Exception as e:
    logger.error(f"Failed to connect to ChromaDB: {e}")

try:
    meili_client = meilisearch.Client(MEILI_HOST, MEILI_MASTER_KEY)
    # Ensure index exists and configure it
    try:
        meili_client.create_index("rag_documents", {"primaryKey": "id"})
        logger.info("Created Meilisearch index")
    except meilisearch.errors.MeilisearchApiError as e:
        if "index_already_exists" not in str(e).lower():
            raise
        logger.info("Meilisearch index already exists")

    index = meili_client.index("rag_documents")
    # Configure searchable attributes for better accuracy
    index.update_searchable_attributes(["text"])
    index.update_filterable_attributes(["source"])
    logger.info("Connected to Meilisearch")
except Exception as e:
    logger.error(f"Failed to connect to Meilisearch: {e}")


# --- ENDPOINTS ---


class Query(BaseModel):
    question: str
    top_k: int = 5


@app.get("/health")
async def health_check():
    chroma_ok = False
    meili_ok = False
    chroma_error = None
    meili_error = None

    if vector_store:
        try:
            vector_store._client.heartbeat()
            chroma_ok = True
        except Exception as e:
            chroma_error = str(e)
            logger.warning(f"ChromaDB health check failed: {e}")

    if meili_client:
        try:
            meili_client.health()
            meili_ok = True
        except Exception as e:
            meili_error = str(e)
            logger.warning(f"Meilisearch health check failed: {e}")

    return {
        "status": "healthy" if (chroma_ok and meili_ok) else "degraded",
        "chroma": {"status": chroma_ok, "error": chroma_error},
        "meilisearch": {"status": meili_ok, "error": meili_error},
    }


@app.get("/stats")
async def get_stats():
    """Get statistics about indexed documents."""
    try:
        stats = {"total_chunks": 0, "unique_documents": 0, "sources": []}

        if meili_client:
            index = meili_client.index("rag_documents")
            index_stats = index.get_stats()
            stats["total_chunks"] = index_stats.get("numberOfDocuments", 0)

            # Get unique sources
            if stats["total_chunks"] > 0:
                # Fetch all documents to count unique sources
                results = index.search("", {"limit": 1000})
                sources = {}
                for hit in results.get("hits", []):
                    source = hit.get("source", "unknown")
                    sources[source] = sources.get(source, 0) + 1

                stats["unique_documents"] = len(sources)
                stats["sources"] = [{"name": k, "chunks": v} for k, v in sources.items()]

        return stats
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/ingest")
async def ingest_pdf(file: UploadFile = File(...)):
    file_path = None
    try:
        # Validate file type
        if not file.filename or not file.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="Only PDF files are supported")

        # Check file size
        file.file.seek(0, 2)  # Seek to end
        file_size = file.file.tell()
        file.file.seek(0)  # Reset to beginning

        if file_size > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=400, detail=f"File too large. Maximum size is {MAX_FILE_SIZE / 1024 / 1024:.0f}MB"
            )

        logger.info(f"Processing file: {file.filename} ({file_size / 1024:.1f}KB)")

        # Use unique filename to avoid collisions
        file_path = f"/tmp/{uuid.uuid4()}_{file.filename}"  # nosec B108 - temp dir is safe in container

        with open(file_path, "wb+") as f:
            shutil.copyfileobj(file.file, f)

        # 1. Parse with Docling
        loader = DoclingLoader(file_path)
        docs = loader.load()

        if not docs:
            raise HTTPException(status_code=400, detail="No text could be extracted from the PDF")

        # 2. Split documents into smaller chunks (for embedding model token limits)
        # nomic-embed-text via Ollama enforces 512 token limit - be very conservative
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=400,  # ~100 tokens (4:1 char:token ratio), very safe for 512 limit
            chunk_overlap=50,  # ~12 tokens overlap for context
            length_function=len,
            separators=["\n\n", "\n", ". ", " ", ""],
        )
        split_docs = text_splitter.split_documents(docs)
        logger.info(f"Split {len(docs)} documents into {len(split_docs)} chunks")

        # 3. Add IDs and Metadata - use consistent IDs for both stores
        doc_ids = []
        meili_docs = []

        # Filter complex metadata that ChromaDB can't handle
        split_docs = filter_complex_metadata(split_docs)

        for i, doc in enumerate(split_docs):
            # Generate stable ID for text chunks
            doc_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{file.filename}_{i}"))
            doc_ids.append(doc_id)
            doc.metadata["source"] = file.filename
            doc.metadata["chunk_index"] = i
            doc.metadata["doc_id"] = doc_id

            # Prepare for Meilisearch (needs explicit ID)
            meili_docs.append({"id": doc_id, "text": doc.page_content, "source": file.filename, "chunk_index": i})

        # 4. Index to Chroma (Vectors) with consistent IDs
        texts = [doc.page_content for doc in split_docs]
        metadatas = [doc.metadata for doc in split_docs]
        vector_store.add_texts(texts=texts, metadatas=metadatas, ids=doc_ids)

        # 5. Index to Meilisearch (Keywords)
        if meili_client:
            meili_client.index("rag_documents").add_documents(meili_docs)

        # Cleanup
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
        return {
            "status": "indexed",
            "filename": file.filename,
            "chunks": len(split_docs),
            "target": "chroma + meilisearch",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error ingesting: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Ensure cleanup even on error
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception as e:
                logger.error(f"Failed to cleanup temp file: {e}")


@app.post("/chat")
async def chat(query: Query):
    if not vector_store or not meili_client:
        raise HTTPException(status_code=503, detail="Search engines not available")

    # 1. Define Retrievers
    chroma_retriever = vector_store.as_retriever(search_kwargs={"k": query.top_k})
    meili_retriever = MeilisearchRetriever(client=meili_client, index_name="rag_documents", k=query.top_k)

    # 2. Hybrid Search (Ensemble)
    # Weights: 0.5 for Vector, 0.5 for Keyword (adjustable)
    ensemble_retriever = EnsembleRetriever(
        retrievers=[chroma_retriever, meili_retriever],
        weights=[0.6, 0.4],  # Give slightly more weight to semantic meaning
    )

    # 3. Chat Chain
    prompt = ChatPromptTemplate.from_template(
        """
    Answer the question based ONLY on the following context.
    If you don't know the answer, say "I don't know".

    <context>
    {context}
    </context>

    Question: {input}
    """
    )

    document_chain = create_stuff_documents_chain(llm, prompt)
    retrieval_chain = create_retrieval_chain(ensemble_retriever, document_chain)

    try:
        # Prepare callbacks for Langfuse tracing
        callbacks = [langfuse_handler] if langfuse_handler else []

        # Add session and user tracking if available
        config = {}
        if langfuse_handler:
            config["callbacks"] = callbacks
            # You can add metadata like user_id, session_id here
            langfuse_handler.trace(
                name="rag_chat_query",
                metadata={
                    "question": query.question,
                    "top_k": query.top_k,
                    "llm_model": LLM_MODEL,
                    "embedding_model": EMBEDDING_MODEL,
                },
            )

        response = retrieval_chain.invoke({"input": query.question}, config=config)

        # Format sources
        sources = []
        for doc in response.get("context", []):
            sources.append({"text": doc.page_content[:200] + "...", "metadata": doc.metadata})

        return {"answer": response["answer"], "sources": sources}

    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Serve frontend
@app.get("/")
async def serve_frontend():
    frontend_path = Path(__file__).parent.parent / "frontend" / "index.html"
    if frontend_path.exists():
        return FileResponse(frontend_path)
    return {"message": "Frontend not found"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)  # nosec B104 - binding to all interfaces is required in k8s
