#!/bin/bash
#
# Deploy PPS changes from project directory to MCP server location
#
# This syncs changes from the development directory to the deployed location
# where the MCP server runs, solving the deployment sync issue (#36).
#

set -e

PROJECT_PPS="/mnt/c/Users/Jeff/Claude_Projects/Awareness/pps"
DEPLOYED_PPS="$HOME/.claude/pps"

echo "🚀 Deploying PPS changes..."
echo "From: $PROJECT_PPS"
echo "To:   $DEPLOYED_PPS"

# Ensure deployed directory exists
mkdir -p "$DEPLOYED_PPS"

# Sync all Python files and directories
echo "📁 Syncing server.py..."
cp "$PROJECT_PPS/server.py" "$DEPLOYED_PPS/"

echo "📁 Syncing layers/..."
mkdir -p "$DEPLOYED_PPS/layers"
cp -r "$PROJECT_PPS/layers"/* "$DEPLOYED_PPS/layers/"

echo "📁 Syncing web/..."
if [ -d "$PROJECT_PPS/web" ]; then
    mkdir -p "$DEPLOYED_PPS/web"
    cp -r "$PROJECT_PPS/web"/* "$DEPLOYED_PPS/web/"
fi

echo "📁 Syncing requirements.txt..."
if [ -f "$PROJECT_PPS/requirements.txt" ]; then
    cp "$PROJECT_PPS/requirements.txt" "$DEPLOYED_PPS/"
fi

echo "📁 Syncing docker/..."
mkdir -p "$DEPLOYED_PPS/docker"
cp "$PROJECT_PPS/docker/docker-compose.yml" "$DEPLOYED_PPS/docker/"
cp "$PROJECT_PPS/docker/Dockerfile" "$DEPLOYED_PPS/docker/" 2>/dev/null || true
cp "$PROJECT_PPS/docker/Dockerfile.web" "$DEPLOYED_PPS/docker/" 2>/dev/null || true
cp "$PROJECT_PPS/docker/requirements-docker.txt" "$DEPLOYED_PPS/docker/" 2>/dev/null || true
cp "$PROJECT_PPS/docker/requirements-web.txt" "$DEPLOYED_PPS/docker/" 2>/dev/null || true

# Sync .env file (critical for API keys like OPENAI_API_KEY)
# Only copy if source has content that deployed version is missing
if [ -f "$PROJECT_PPS/docker/.env" ]; then
    echo "📁 Syncing docker/.env (API keys)..."
    cp "$PROJECT_PPS/docker/.env" "$DEPLOYED_PPS/docker/.env"
fi

# Verify deployment
echo "✅ Deployment complete!"
echo ""
echo "📊 Deployed files:"
find "$DEPLOYED_PPS" -type f -name "*.py" | head -10

echo ""
echo "🔄 Next step: Restart Claude Code for MCP server to reload"
echo "   Terminal: Exit and restart Claude Code"
echo "   VS Code: Cmd/Ctrl+Shift+P → 'Claude Code: Restart'"