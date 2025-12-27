# Langfuse Setup Guide

This guide explains how to deploy and configure self-hosted Langfuse for observability and tracing in your RAG application.

## Overview

Langfuse provides:
- **Trace Logging**: Track every LLM call, retrieval, and chain execution
- **Cost Analysis**: Monitor token usage and costs
- **Performance Metrics**: Measure latency and throughput
- **Prompt Management**: Version and test prompts
- **User Analytics**: Track queries and user patterns

## Architecture

```
┌─────────────┐
│  RAG API    │
│  (FastAPI)  │
└──────┬──────┘
       │ Langfuse Callback
       ▼
┌─────────────┐     ┌──────────────┐
│  Langfuse   │────▶│  PostgreSQL   │
│   Web UI    │     │   Database    │
└──────┬──────┘     └──────────────┘
  │
  │ background jobs / ingestion
  ▼
┌─────────────┐     ┌──────────────┐
│  Langfuse   │────▶│  ClickHouse   │
│   Worker    │     │ (analytics)   │
└──────┬──────┘     └──────────────┘
  │
  ├────────────▶ Redis (queue/cache)
  │
  └────────────▶ S3/MinIO (blob storage)
```

## Prerequisites

- Kubernetes cluster with llm-stack namespace
- kubectl access to the cluster
- Updated ConfigMap and Secrets (already configured)

## Deployment Steps

### 1. Apply the Secrets and ConfigMap

The secrets and config have already been added to:
- `manifests/000-config.yaml` - Langfuse configuration
- `manifests/001-secrets.yaml` - Langfuse credentials

**Important Security Note**: The provided secrets are **sample values** for development. In production:

```bash
# Generate secure random secrets
NEXTAUTH_SECRET=$(openssl rand -base64 32)
SALT=$(openssl rand -base64 16)
PUBLIC_KEY="pk-lf-$(openssl rand -hex 8)"
SECRET_KEY="sk-lf-$(openssl rand -hex 16)"  # pragma: allowlist secret
ADMIN_PASSWORD=$(openssl rand -base64 16)

# Base64 encode them
echo -n "$NEXTAUTH_SECRET" | base64
echo -n "$SALT" | base64
echo -n "$PUBLIC_KEY" | base64
echo -n "$SECRET_KEY" | base64  # pragma: allowlist secret
echo -n "$ADMIN_PASSWORD" | base64
```

Update the secrets in `001-secrets.yaml` with your generated values.

### 2. Deploy Langfuse

```bash
# Apply in order
kubectl apply -f manifests/000-config.yaml
kubectl apply -f manifests/001-secrets.yaml
kubectl apply -f manifests/08-langfuse.yaml

# Wait for PostgreSQL to be ready
kubectl wait --for=condition=ready pod -l app=langfuse-postgres -n llm-stack --timeout=300s

# Wait for ClickHouse to be ready
kubectl wait --for=condition=ready pod -l app=langfuse-clickhouse -n llm-stack --timeout=300s

# Wait for Redis to be ready
kubectl wait --for=condition=ready pod -l app=langfuse-redis -n llm-stack --timeout=300s

# Wait for MinIO to be ready
kubectl wait --for=condition=ready pod -l app=langfuse-minio -n llm-stack --timeout=300s

# Wait for Langfuse to be ready
kubectl wait --for=condition=ready pod -l app=langfuse -n llm-stack --timeout=300s

# Wait for worker to be ready
kubectl wait --for=condition=ready pod -l app=langfuse-worker -n llm-stack --timeout=300s
```

### 3. Verify Deployment

```bash
# Check pods
kubectl get pods -n llm-stack | grep langfuse

# Check logs
kubectl logs -n llm-stack -l app=langfuse --tail=50

# Port forward to access UI
kubectl port-forward -n llm-stack svc/langfuse 3000:3000
```

Open browser to http://localhost:3000

### 4. Initial Login

This setup does not auto-create an initial admin user.

1. Port-forward the service:

```bash
kubectl port-forward -n llm-stack svc/langfuse 3000:3000
```

2. Open http://localhost:3000 and create the first user via the UI.

### 5. Get API Keys

After login:
1. Go to Settings → Projects
2. Create a project (e.g. "RAG Application")
3. Create API keys and copy the Public/Secret key values

Update these secrets to match your project keys:
- `llm-infrastructure/manifests/001-secrets.yaml`: `langfuse-public-key`, `langfuse-secret-key`

Then restart the RAG API deployment.

### 6. Deploy/Redeploy RAG API

```bash
# Apply updated RAG API with Langfuse integration
kubectl apply -f rag-app/k8s/02-rag-api.yaml

# Restart RAG API to pick up new config
kubectl rollout restart deployment/rag-api -n llm-stack

# Check logs for Langfuse connection
kubectl logs -n llm-stack -l app=rag-api --tail=50 | grep -i langfuse
```

## Configuration

### Environment Variables in RAG API

| Variable | Description | Default |
|----------|-------------|---------|
| `LANGFUSE_HOST` | Langfuse server URL | `http://langfuse.llm-stack.svc.cluster.local:3000` |
| `LANGFUSE_PUBLIC_KEY` | Project public key | From secret |
| `LANGFUSE_SECRET_KEY` | Project secret key | From secret |
| `LANGFUSE_ENABLED` | Enable/disable tracing | `true` |

### Disable Langfuse (Optional)

To disable tracing without redeploying:

```bash
kubectl set env deployment/rag-api -n llm-stack LANGFUSE_ENABLED=false
```

## Usage

### Viewing Traces

1. Access Langfuse UI: http://localhost:3000 (via port-forward)
2. Navigate to "Traces" section
3. Each chat query creates a trace showing:
   - Query input
   - Retrieval results
   - LLM calls
   - Token usage
   - Latency
   - Response

### Understanding Traces

A typical RAG trace includes:
```
rag_chat_query (root)
  ├─ retrieval (ensemble)
  │   ├─ chroma_retriever (vector search)
  │   └─ meilisearch_retriever (keyword search)
  └─ llm_call
      ├─ prompt
      ├─ completion
      └─ tokens (prompt: X, completion: Y, total: Z)
```

### Analyzing Performance

- **Dashboard**: Overview of requests, tokens, costs
- **Sessions**: Group related queries by user/session
- **Scores**: Add feedback scores to responses
- **Prompts**: Version and test different prompts

## Troubleshooting

### Langfuse Pod Not Starting

```bash
# Check dependencies first
kubectl logs -n llm-stack -l app=langfuse-postgres --tail=50
kubectl logs -n llm-stack -l app=langfuse-clickhouse --tail=50
kubectl logs -n llm-stack -l app=langfuse-redis --tail=50
kubectl logs -n llm-stack -l app=langfuse-minio --tail=50

# Check Langfuse components
kubectl logs -n llm-stack -l app=langfuse --tail=100
kubectl logs -n llm-stack -l app=langfuse-worker --tail=100

# Common issues:
# - "Invalid environment variables": a required env var is missing in the Deployment
# - ClickHouse URL format: CLICKHOUSE_URL must be http(s)://...:8123 and CLICKHOUSE_MIGRATION_URL must be clickhouse://...:9000
# - MinIO buckets: check the langfuse-minio-init job logs
```

### RAG API Not Connecting to Langfuse

```bash
# Check RAG API logs
kubectl logs -n llm-stack -l app=rag-api --tail=50 | grep -i langfuse

# Should see: "Langfuse observability enabled at ..."

# Verify secrets are mounted
kubectl exec -n llm-stack deployment/rag-api -- env | grep LANGFUSE

# Test connectivity from RAG pod
kubectl exec -n llm-stack deployment/rag-api -- curl -I http://langfuse.llm-stack.svc.cluster.local:3000/api/public/health
```

### No Traces Appearing

1. **Verify API keys match**: Check Langfuse UI project keys vs. secrets
2. **Check network**: Ensure RAG API can reach Langfuse service
3. **Test manually**:
   ```bash
   # Send a test query
   kubectl port-forward -n llm-stack svc/rag-api 8080:80
   curl -X POST http://localhost:8080/chat \
     -H "Content-Type: application/json" \
     -d '{"question": "test query"}'
   ```
4. **Check Langfuse logs** for incoming requests

### Database Issues

```bash
# Connect to PostgreSQL
kubectl exec -it -n llm-stack langfuse-postgres-0 -- psql -U langfuse -d langfuse

# Check tables
\dt

# Check recent traces
SELECT id, name, timestamp FROM traces ORDER BY timestamp DESC LIMIT 10;
```

## Production Considerations

### Security

1. **Change all default passwords immediately**
2. **Use strong, random secrets** (see step 1)
3. **Enable TLS/SSL** for PostgreSQL connections
4. **Restrict network access** to Langfuse UI
5. **Use RBAC** for Kubernetes access control

### Scaling

1. **Database**: Increase PostgreSQL resources for high volume
   ```yaml
   resources:
     requests:
       memory: "2Gi"
       cpu: "1000m"
   ```

2. **Langfuse**: Scale horizontally for high traffic
   ```bash
   kubectl scale deployment langfuse -n llm-stack --replicas=3
   ```

3. **Storage**: Increase PVC size as traces grow
   ```bash
   # Edit PVC (requires storage class that supports resize)
   kubectl edit pvc langfuse-postgres-storage -n llm-stack
   ```

### Backup

```bash
# Backup PostgreSQL database
kubectl exec -n llm-stack langfuse-postgres-0 -- \
  pg_dump -U langfuse langfuse > langfuse-backup-$(date +%Y%m%d).sql

# Restore
kubectl exec -i -n llm-stack langfuse-postgres-0 -- \
  psql -U langfuse -d langfuse < langfuse-backup-20261226.sql
```

### Monitoring

Add Prometheus metrics (optional):
```yaml
# In langfuse deployment
env:
  - name: PROMETHEUS_ENABLED
    value: "true"
```

## Exposing Langfuse UI

### Option 1: Port Forward (Development)
```bash
kubectl port-forward -n llm-stack svc/langfuse 3000:3000
```

### Option 2: Ingress (Production)
```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: langfuse-ingress
  namespace: llm-stack
spec:
  rules:
  - host: langfuse.yourdomain.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: langfuse
            port:
              number: 3000
```

### Option 3: Cloudflare Tunnel (Existing Setup)

Add to your `05-tunnel.yaml`:
```yaml
- hostname: langfuse.yourdomain.com
  service: http://langfuse.llm-stack.svc.cluster.local:3000
```

## API Reference

For advanced usage, see:
- [Langfuse Python SDK](https://langfuse.com/docs/sdk/python)
- [LangChain Integration](https://langfuse.com/docs/integrations/langchain)
- [REST API](https://langfuse.com/docs/api)

## Resources

- Langfuse Documentation: https://langfuse.com/docs
- GitHub: https://github.com/langfuse/langfuse
- Self-Hosting Guide: https://langfuse.com/docs/deployment/self-host
