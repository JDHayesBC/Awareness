#!/usr/bin/env bash
# Launch @playwright/mcp under nvm's node.
#
# Why this wrapper exists: Claude Code launches MCP servers with a bare
# environment whose PATH resolves `npx` to the system node (/usr/bin/node,
# currently v18). @playwright/mcp now requires Node >= 20, so it exits
# immediately and the harness reports it as "Connection closed" /
# "authentication failed". We prepend the newest nvm-installed node to PATH
# so the correct interpreter is used. Survives nvm version bumps (picks the
# highest installed vNN automatically).
set -euo pipefail

NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
node_bin="$(ls -d "$NVM_DIR"/versions/node/v* 2>/dev/null | sort -V | tail -1)/bin"

if [ -x "$node_bin/node" ]; then
  export PATH="$node_bin:$PATH"
fi

exec npx @playwright/mcp@latest "$@"
