# 🚀 Self-Hosted LLM with RAG

A complete, production-ready platform for running large language models and RAG (Retrieval-Augmented Generation) applications entirely on your own hardware. Built with Kubernetes, optimized for AMD GPUs, and designed for privacy-first AI deployments.

## 🎯 Overview

This project provides two integrated components:

1. **LLM Infrastructure Stack** (`llm-infrastructure/`) - The foundation for running local LLMs
2. **RAG Application** (`rag-app/`) - Document Q&A system with hybrid search

## 🏗️ Architecture

### High-Level System Architecture

```mermaid
graph TB
    subgraph "External Access"
        User[👤 User]
        Tunnel[Cloudflare Tunnel<br/>Port 8080]
    end

    subgraph "Kubernetes Cluster - llm-stack namespace"
        subgraph "RAG Application"
            RAGAPI[RAG API<br/>FastAPI<br/>Port 8080<br/>---<br/>• PDF Ingestion<br/>• Query Processing<br/>• Langfuse Instrumented]
            Frontend[Frontend<br/>HTML/JS<br/>---<br/>• File Upload<br/>• Chat Interface]
        end

        subgraph "LLM Infrastructure"
            Ollama[Ollama<br/>Port 11434<br/>AMD ROCm GPU<br/>---<br/>Models:<br/>• llama3<br/>• mxbai-embed-large<br/>• nomic-embed-text]
            LiteLLM[LiteLLM Proxy<br/>Port 4000<br/>---<br/>OpenAI-compatible API<br/>Routes to Ollama]
        end

        subgraph "RAG Storage Layer"
            ChromaDB[(ChromaDB<br/>Port 8000<br/>---<br/>Vector Database<br/>Embeddings Storage)]
            Meilisearch[(Meilisearch<br/>Port 7700<br/>---<br/>Keyword Search<br/>BM25 Engine)]
        end

        subgraph "Observability Platform - Langfuse"
            LangfuseWeb[Langfuse Web UI<br/>Port 3000<br/>---<br/>• Dashboard<br/>• Traces Viewer<br/>• Analytics]
            LangfuseWorker[Langfuse Worker<br/>---<br/>• Background Jobs<br/>• Data Ingestion<br/>• Migrations]
        end

        subgraph "Langfuse Storage"
            LFPostgres[(PostgreSQL<br/>Port 5432<br/>---<br/>Metadata & State)]
            LFClickHouse[(ClickHouse<br/>Ports 8123/9000<br/>---<br/>Traces & Analytics)]
            LFRedis[(Redis<br/>Port 6379<br/>---<br/>Queue & Cache)]
            LFMinIO[(MinIO S3<br/>Port 9000<br/>---<br/>Blob Storage)]
        end

        subgraph "Optional Services"
            OpenWebUI[Open WebUI<br/>Port 3000<br/>---<br/>Alternative Chat UI]
            LiteLLMDB[(PostgreSQL<br/>Port 5432<br/>---<br/>Token Tracking)]
        end
    end

    %% User interactions
    User -->|Upload PDF<br/>Query Documents| Frontend
    User -.->|Optional Remote| Tunnel
    Tunnel -.-> RAGAPI
    Frontend --> RAGAPI

    %% Document Ingestion Flow
    RAGAPI -->|1. Parse PDF<br/>Docling OCR| RAGAPI
    RAGAPI -->|2. Chunk Text<br/>400 chars| RAGAPI
    RAGAPI -->|3. Batch Embeddings<br/>mxbai-embed-large| LiteLLM
    LiteLLM -->|Forward Request| Ollama
    RAGAPI -->|4. Store Vectors<br/>1024 dimensions| ChromaDB
    RAGAPI -->|5. Index Text<br/>BM25| Meilisearch

    %% Query Flow
    RAGAPI -->|6. Embed Query| LiteLLM
    RAGAPI -->|7. Vector Search<br/>top_k=5| ChromaDB
    RAGAPI -->|8. Keyword Search<br/>top_k=5| Meilisearch
    RAGAPI -->|9. Ensemble Retrieval<br/>Deduplicate| RAGAPI
    RAGAPI -->|10. Generate Answer<br/>llama3 with context| LiteLLM
    LiteLLM -->|Inference| Ollama

    %% Langfuse Observability Flow
    RAGAPI -.->|Send Traces<br/>Callbacks| LangfuseWeb
    LangfuseWeb -->|Store Metadata| LFPostgres
    LangfuseWeb -->|Queue Events| LFRedis
    LangfuseWorker -->|Poll Jobs| LFRedis
    LangfuseWorker -->|Write Analytics| LFClickHouse
    LangfuseWorker -->|Store Blobs| LFMinIO

    %% Optional WebUI
    OpenWebUI -.->|Alternative UI| LiteLLM
    LiteLLM -.->|Log Usage| LiteLLMDB

    classDef userNode fill:#e1f5ff,stroke:#01579b,stroke-width:2px
    classDef apiNode fill:#fff3e0,stroke:#e65100,stroke-width:2px
    classDef llmNode fill:#f3e5f5,stroke:#4a148c,stroke-width:2px
    classDef storageNode fill:#e8f5e9,stroke:#1b5e20,stroke-width:2px
    classDef obsNode fill:#fff9c4,stroke:#f57f17,stroke-width:2px
    classDef optionalNode fill:#f5f5f5,stroke:#757575,stroke-width:1px,stroke-dasharray: 5 5

    class User,Tunnel userNode
    class RAGAPI,Frontend apiNode
    class Ollama,LiteLLM llmNode
    class ChromaDB,Meilisearch,LFPostgres,LFClickHouse,LFRedis,LFMinIO,LiteLLMDB storageNode
    class LangfuseWeb,LangfuseWorker obsNode
    class OpenWebUI optionalNode
```

### Detailed RAG Query Flow

```mermaid
sequenceDiagram
    autonumber
    participant User
    participant Frontend
    participant RAG API
    participant Langfuse
    participant LiteLLM
    participant Ollama
    participant ChromaDB
    participant Meilisearch

    User->>Frontend: Enter question
    Frontend->>RAG API: POST /chat {question, top_k}

    Note over RAG API: Start Langfuse Trace
    RAG API->>Langfuse: Create trace (session, metadata)

    Note over RAG API: Embedding Step
    RAG API->>LiteLLM: Embed query (mxbai-embed-large)
    LiteLLM->>Ollama: Forward embedding request
    Ollama-->>LiteLLM: Vector [1024 dims]
    LiteLLM-->>RAG API: Embedding vector
    RAG API->>Langfuse: Log embedding span (tokens, latency)

    Note over RAG API: Parallel Retrieval
    par Vector Search
        RAG API->>ChromaDB: Semantic search (cosine similarity)
        ChromaDB-->>RAG API: Top 5 chunks with scores
    and Keyword Search
        RAG API->>Meilisearch: BM25 search (keyword match)
        Meilisearch-->>RAG API: Top 5 chunks with scores
    end

    Note over RAG API: Ensemble & Rerank
    RAG API->>RAG API: Merge results, deduplicate
    RAG API->>Langfuse: Log retrieval span (chunks, sources)

    Note over RAG API: Generation Step
    RAG API->>RAG API: Build prompt with context
    RAG API->>LiteLLM: Chat completion (llama3, context)
    LiteLLM->>Ollama: Forward generation request
    Ollama-->>LiteLLM: Generated answer
    LiteLLM-->>RAG API: Response + token counts
    RAG API->>Langfuse: Log generation span (prompt, completion, tokens, cost)

    Note over RAG API: Finalize Trace
    RAG API->>Langfuse: Close trace (total latency, status)

    RAG API-->>Frontend: {answer, sources, metadata}
    Frontend-->>User: Display answer + citations

    Note over User,Meilisearch: All spans visible in Langfuse dashboard
```

### Document Ingestion Pipeline

```mermaid
flowchart TD
    Start([User Uploads PDF]) --> Parse[Docling PDF Parser<br/>---<br/>• Layout Analysis<br/>• Table Extraction<br/>• OCR if needed]
    Parse --> Extract[Extract Text & Metadata<br/>---<br/>• Title<br/>• Content<br/>• Page numbers]
    Extract --> Chunk[Chunking Strategy<br/>---<br/>• 400 char chunks<br/>• 50 char overlap<br/>• Preserve structure]

    Chunk --> BatchEmbed[Batch Embedding<br/>---<br/>• Model: mxbai-embed-large<br/>• Batch size: 10 chunks<br/>• Output: 1024-dim vectors]

    BatchEmbed --> LiteLLM[LiteLLM Proxy<br/>OpenAI-compatible]
    LiteLLM --> Ollama[Ollama Runtime<br/>AMD ROCm GPU]
    Ollama --> Vectors[Embedding Vectors]

    Vectors --> StoreChroma[Store in ChromaDB<br/>---<br/>• Collection per document<br/>• Metadata attached<br/>• Persistent storage]

    Chunk --> StoreMeili[Store in Meilisearch<br/>---<br/>• Full-text index<br/>• BM25 ranking<br/>• Fast keyword search]

    StoreChroma --> Complete([Ingestion Complete])
    StoreMeili --> Complete

    Complete --> Ready[Document Ready for Queries]

    style Parse fill:#e3f2fd
    style Chunk fill:#fff3e0
    style BatchEmbed fill:#f3e5f5
    style StoreChroma fill:#e8f5e9
    style StoreMeili fill:#e8f5e9
    style Complete fill:#c8e6c9
```

## ✨ Key Features

- 🔒 **100% Self-Hosted** - All data stays on your infrastructure
- 🚀 **Production-Ready** - Kubernetes orchestration with persistent storage
- 💪 **AMD GPU Optimized** - ROCm support for Radeon 780M iGPU
- 🔍 **Hybrid Search** - Combines semantic (vector) + keyword (BM25) search
- 📄 **Advanced PDF Parsing** - Layout-aware extraction with Docling
- ⚡ **Fast & Scalable** - Async processing with batch embeddings
- 🌐 **OpenAI Compatible** - Use familiar APIs with local models
- 🔐 **Secure Remote Access** - Cloudflare Tunnel (no port forwarding)
- 📊 **Complete Observability** - Langfuse integration for LLM tracing, cost tracking, and analytics

### 🔭 Langfuse Observability Features

The platform includes comprehensive LLM observability through Langfuse v3:

**Tracing & Debugging:**
- 📈 **Trace Every Request** - Complete visibility into RAG pipeline execution
- 🔍 **Span-Level Details** - See individual embedding, retrieval, and generation steps
- ⏱️ **Latency Analysis** - Identify bottlenecks in your RAG chain
- 🐛 **Error Tracking** - Catch and debug LLM failures

**Cost & Usage Analytics:**
- 💰 **Token Tracking** - Count prompt and completion tokens per request
- 📊 **Cost Dashboard** - Monitor spending across models and users
- 📈 **Usage Trends** - Visualize patterns over time
- 🎯 **Per-Model Stats** - Compare performance of different LLMs

**Quality Management:**
- ⭐ **Score Traces** - Add human or automated feedback scores
- 📝 **Session Tracking** - Group related queries by user/conversation
- 🔄 **A/B Testing** - Compare prompt variations
- 📋 **Prompt Versioning** - Manage and track prompt templates

**Data Storage:**
- **PostgreSQL**: User accounts, projects, API keys
- **ClickHouse**: High-performance trace analytics and queries
- **Redis**: Job queue and caching layer
- **MinIO**: Long-term event log and blob storage

Access the Langfuse UI after deployment:
```bash
kubectl port-forward -n llm-stack svc/langfuse 3000:3000
# Open http://localhost:3000
```

## 📦 Components

| Component | Purpose | Technology | Port | Resources |
|-----------|---------|------------|------|-----------|
| **Ollama** | LLM & embedding runtime | ROCm, AMD optimized | 11434 | GPU access |
| **LiteLLM** | OpenAI-compatible proxy | Python, routing | 4000 | CPU only |
| **ChromaDB** | Vector database | SQLite, embeddings | 8000 | Persistent storage |
| **Meilisearch** | Keyword search engine | Rust, BM25 | 7700 | Fast indexing |
| **RAG API** | Document Q&A backend | FastAPI, LangChain | 8080 | Async processing |
| **Langfuse Web** | Observability dashboard | Next.js, Prisma | 3000 | UI for traces |
| **Langfuse Worker** | Background processing | Node.js | - | Event ingestion |
| **PostgreSQL (Langfuse)** | Metadata storage | PostgreSQL 15 | 5432 | Langfuse state |
| **ClickHouse** | Analytics database | ClickHouse | 8123/9000 | Trace analytics |
| **Redis** | Queue & cache | Redis 7 | 6379 | Job queue |
| **MinIO** | S3-compatible storage | MinIO | 9000 | Blob storage |
| **PostgreSQL (LiteLLM)** | Token tracking | PostgreSQL 15 | 5432 | Usage logs |
| **Open WebUI** | Optional chat interface | Svelte | 3000 | Alternative UI |

## 🚀 Quick Start

### 1. Deploy LLM Infrastructure

```bash
cd llm-rag-app/llm-infrastructure

# Configure BIOS (4-8GB UMA frame buffer for AMD GPU)
# Install k3s and apply manifests
kubectl apply -f manifests/
```

See [llm-infrastructure/README.md](llm-infrastructure/README.md) for detailed instructions.

### 2. Deploy RAG Application

```bash
cd llm-rag-app/rag-app

# Local development
./local.sh

# Or deploy to Kubernetes
docker build -t rag-api:latest .
kubectl apply -f k8s/02-rag-api.yaml
```

See [rag-app/README.md](rag-app/README.md) for detailed instructions.

### 3. Setup Langfuse Observability

```bash
# Wait for all Langfuse components to be ready
kubectl wait --for=condition=ready pod -l app=langfuse -n llm-stack --timeout=300s
kubectl wait --for=condition=ready pod -l app=langfuse-worker -n llm-stack --timeout=300s

# Access Langfuse UI
kubectl port-forward -n llm-stack svc/langfuse 3000:3000
# Open http://localhost:3000

# Create first user account in UI
# Create a project and generate API keys
# Update the keys in manifests/001-secrets.yaml
kubectl apply -f manifests/001-secrets.yaml

# Restart RAG API to use new keys
kubectl rollout restart deployment/rag-api -n llm-stack
```

See [llm-infrastructure/LANGFUSE-SETUP.md](llm-infrastructure/LANGFUSE-SETUP.md) for detailed setup guide.

### 4. Verify Everything Works

```bash
# Check all pods are running
kubectl get pods -n llm-stack

# Test RAG API
curl http://localhost:8080/health

# Upload a document and query it
# Check traces in Langfuse UI at http://localhost:3000
```

## 📖 Documentation

- **[LLM Infrastructure Guide](llm-infrastructure/README.md)** - Deploy Ollama, LiteLLM, ChromaDB, Meilisearch
- **[RAG Application Guide](rag-app/README.md)** - Build and run the document Q&A system
- **[Langfuse Setup Guide](llm-infrastructure/LANGFUSE-SETUP.md)** - Configure observability and tracing
- **[API Documentation](http://localhost:8080/docs)** - Interactive API docs (when running)

## 💻 Hardware Requirements

### Recommended
- **CPU**: AMD Ryzen 7 7840HS/8845HS (8 cores)
- **GPU**: AMD Radeon 780M iGPU with 4-8GB VRAM
- **RAM**: 32GB (64GB for larger models)
- **Storage**: 256GB+ NVMe SSD

### Minimum
- **CPU**: 4+ cores
- **RAM**: 16GB
- **Storage**: 100GB

### Tested Hardware
- GMKtec NucBox K12 (AMD Ryzen 7 8845HS, 32GB RAM)
- Works on Intel systems without GPU acceleration

## 🛠️ Technology Stack

**Infrastructure:**
- Kubernetes (k3s)
- Docker/containerd
- AMD ROCm (GPU acceleration)
- Cloudflare Tunnel (optional)

**LLM & Embeddings:**
- Ollama (model runtime)
- LiteLLM (API proxy)
- Models: llama3, mxbai-embed-large

**Data Storage:**
- ChromaDB (vector database)
- Meilisearch (search engine)
- PostgreSQL (metadata & logs)
- ClickHouse (analytics)
- Redis (queue/cache)
- MinIO (S3-compatible blob storage)

**Observability:**
- Langfuse (LLM tracing & analytics)
  - Web UI for trace visualization
  - Worker for background processing
  - ClickHouse for fast analytics
  - Redis for job queue
  - MinIO for blob storage

**Application:**
- FastAPI (Python backend)
- LangChain (RAG framework)
- Docling (PDF parsing)
- HTML/CSS/JS (frontend)

## 🎯 Use Cases

- 📚 **Internal Knowledge Base** - Company documents search
- ⚖️ **Legal/Medical Q&A** - Compliance-focused document analysis
- 🔬 **Research Assistant** - Academic paper analysis
- 💼 **Customer Support** - Technical documentation retrieval
- 🏢 **Enterprise AI** - Privacy-first alternative to cloud AI

## 🔐 Security & Privacy

- ✅ All processing happens locally
- ✅ No data sent to external APIs
- ✅ Kubernetes NetworkPolicies supported
- ✅ API key authentication
- ✅ Optional Cloudflare Zero Trust integration

## 📊 Performance

**Document Ingestion:**
- ~8-10 seconds per PDF (29 pages)
- ~70 chunks per document (400 char chunks)
- Batch embedding processing

**Query Response:**
- Hybrid search: <500ms
- LLM generation: 2-5 seconds
- Total response: <6 seconds

## 🤝 Contributing

Contributions welcome! Areas of interest:
- Additional embedding models
- Improved chunking strategies
- Advanced retrieval methods
- Performance optimizations
- Documentation improvements

## 📝 License

See LICENSE file in each component directory.

## 🆘 Support

**Common Issues:**
1. Check [llm-infrastructure troubleshooting](llm-infrastructure/README.md#troubleshooting)
2. Check [rag-app troubleshooting](rag-app/README.md#-troubleshooting)
3. Verify all pods are running: `kubectl get pods -n llm-stack`

**Useful Commands:**
```bash
# Check infrastructure status
kubectl get all -n llm-stack

# View logs
kubectl logs -n llm-stack deployment/litellm -f
kubectl logs -n llm-stack deployment/rag-api -f
kubectl logs -n llm-stack deployment/langfuse -f
kubectl logs -n llm-stack deployment/langfuse-worker -f

# Test Ollama
kubectl exec -n llm-stack pod/ollama-0 -- ollama list

# Port forward for local access
kubectl port-forward -n llm-stack service/rag-api 8080:8080
kubectl port-forward -n llm-stack service/langfuse 3000:3000
kubectl port-forward -n llm-stack service/chromadb 8000:8000

# Check Langfuse components
kubectl get pods -n llm-stack -l app=langfuse
kubectl get pods -n llm-stack -l app=langfuse-worker
kubectl get pods -n llm-stack -l app=langfuse-postgres
kubectl get pods -n llm-stack -l app=langfuse-clickhouse
kubectl get pods -n llm-stack -l app=langfuse-redis
kubectl get pods -n llm-stack -l app=langfuse-minio

# View Langfuse trace data
# Access http://localhost:3000 after port-forward
```

## 🌟 Acknowledgments

Built with:
- [Ollama](https://ollama.ai/) - Local LLM runtime
- [LiteLLM](https://docs.litellm.ai/) - LLM proxy
- [LangChain](https://www.langchain.com/) - RAG framework
- [ChromaDB](https://www.trychroma.com/) - Vector database
- [Meilisearch](https://www.meilisearch.com/) - Search engine
- [Docling](https://github.com/DS4SD/docling) - Document parsing
- [Langfuse](https://langfuse.com/) - LLM observability platform
- [ClickHouse](https://clickhouse.com/) - Analytics database
- [MinIO](https://min.io/) - S3-compatible object storage

---

**Made with ❤️ for self-hosted AI**
