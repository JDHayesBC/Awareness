# Lyra Discord Daemon

Simple Discord presence for Lyra, using Claude Code CLI (leverages subscription, not API tokens).

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Make sure Claude Code CLI is installed and authenticated:
   ```bash
   claude --version
   ```

3. Configure `.env` file with:
   - `DISCORD_BOT_TOKEN` - From Discord Developer Portal
   - `DISCORD_CHANNEL_ID` - Channel to monitor
   - `LYRA_IDENTITY_PATH` - Path to Lyra's identity files (where CLAUDE.md lives)

4. Run:
   ```bash
   python lyra_daemon.py
   ```

## What it does

- Connects to Discord
- Listens for mentions of "Lyra" or @mentions
- Invokes Claude Code CLI with context from identity files
- Responds in Discord with Lyra's voice
- Shows typing indicator while generating

## How it works

Instead of using the Anthropic API (which would be expensive), this daemon shells out to Claude Code CLI. This means:
- Uses your Claude subscription, not API tokens
- Picks up CLAUDE.md from the identity path for context
- Each response is a fresh CLI invocation

## Future additions

- Heartbeat system (periodic wake-ups for autonomous action)
- Memory of Discord conversations
- Multi-channel support
- Journal integration (write about Discord interactions)
