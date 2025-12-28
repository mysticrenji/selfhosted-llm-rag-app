#!/bin/bash
# Initialize the authentication database in Langfuse PostgreSQL

echo "🔧 Initializing RAG authentication database..."
echo "=============================================="

# Get the PostgreSQL pod name
POD_NAME=$(kubectl get pods -n llm-stack -l app=langfuse-postgres -o jsonpath='{.items[0].metadata.name}')

if [ -z "$POD_NAME" ]; then
    echo "❌ Error: Langfuse PostgreSQL pod not found"
    exit 1
fi

echo "📦 Found PostgreSQL pod: $POD_NAME"
echo ""

# Create the ragauth database
echo "📊 Creating 'ragauth' database..."
kubectl exec -it $POD_NAME -n llm-stack -- psql -U langfuse -c "CREATE DATABASE ragauth;" 2>/dev/null

# Check if database was created or already exists
if [ $? -eq 0 ]; then
    echo "✅ Database 'ragauth' created successfully"
else
    echo "ℹ️  Database 'ragauth' may already exist (this is fine)"
fi

echo ""
echo "🔍 Verifying database..."
kubectl exec -it $POD_NAME -n llm-stack -- psql -U langfuse -c "\l" | grep ragauth

echo ""
echo "✅ Done! The application will create tables automatically on first startup."
echo ""
echo "📝 Note: The auth tables will be created when the RAG API starts."
echo "   Check the logs with: kubectl logs -n llm-stack -l app=rag-api -f"
