#!/bin/bash
# Create a deployable package of the PPS for distribution

set -e

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Package name with timestamp
PACKAGE_NAME="pps-deploy-$(date +%Y%m%d-%H%M%S)"
PACKAGE_DIR="/tmp/$PACKAGE_NAME"

echo "Creating PPS deployment package..."

# Create package directory
mkdir -p "$PACKAGE_DIR"

# Copy essential files
echo "Copying files..."
cp -r docker/ "$PACKAGE_DIR/"
cp -r layers/ "$PACKAGE_DIR/"
cp -r deploy/ "$PACKAGE_DIR/"
cp server.py "$PACKAGE_DIR/"
cp server.py "$PACKAGE_DIR/"
cp requirements.txt "$PACKAGE_DIR/"
cp README.md "$PACKAGE_DIR/"
cp DEPLOYMENT.md "$PACKAGE_DIR/"

# Create a simple installer at the root
cat > "$PACKAGE_DIR/INSTALL.md" << 'EOF'
# Pattern Persistence System - Quick Install

## Option 1: Automated Setup (Recommended)

Run the setup script:
```bash
cd deploy
./setup.sh
```

## Option 2: Manual Setup

See DEPLOYMENT.md for detailed instructions.

## What's Included

- `docker/` - Docker Compose configuration
- `layers/` - PPS layer implementations  
- `deploy/` - Setup script and examples
- `server.py` - MCP server for Claude Code
- `DEPLOYMENT.md` - Full deployment guide

## Quick Test

After setup, test with:
```bash
curl http://localhost:8201/health
```

EOF

# Create archive
cd /tmp
tar -czf "$PACKAGE_NAME.tar.gz" "$PACKAGE_NAME"

# Move to script directory
mv "$PACKAGE_NAME.tar.gz" "$SCRIPT_DIR/"

# Cleanup
rm -rf "$PACKAGE_DIR"

echo "Package created: $SCRIPT_DIR/$PACKAGE_NAME.tar.gz"
echo
echo "To deploy on another machine:"
echo "1. Copy $PACKAGE_NAME.tar.gz to the target machine"
echo "2. Extract: tar -xzf $PACKAGE_NAME.tar.gz"
echo "3. Follow instructions in INSTALL.md"