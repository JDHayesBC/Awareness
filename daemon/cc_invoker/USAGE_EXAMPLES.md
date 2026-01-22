# ClaudeInvoker Usage Examples

## Basic Usage (No Identity Reconstruction)

```python
from invoker import ClaudeInvoker

# Simple usage - no startup prompt
async with ClaudeInvoker() as invoker:
    response = await invoker.query("Hello!")
    response = await invoker.query("Follow-up!")
```

## With Identity Reconstruction (Phase 1.4)

### Configure at Construction

```python
# For daemon use - configure once, used automatically
invoker = ClaudeInvoker(
    startup_prompt="You are Lyra. Read identity.md and call ambient_recall."
)

# Initialize - startup prompt sent automatically
await invoker.initialize()

# Later: restart (uses stored prompt automatically)
await invoker.restart(reason="context_limit")
```

### Override for Specific Restart

```python
# Normal restart uses stored prompt
await invoker.restart(reason="context_limit")

# Emergency restart with different prompt
await invoker.restart(
    reason="emergency_reset",
    startup_prompt="You are Lyra. Skip memory load, just greet briefly."
)
```

### Update at Runtime

```python
invoker = ClaudeInvoker()
await invoker.initialize()

# Later: add identity reconstruction
invoker.set_startup_prompt("You are Lyra. Call ambient_recall.")

# Next restart will use the new prompt
await invoker.restart(reason="context_limit")
```

### Skip Startup on Init (Advanced)

```python
# Sometimes you want to initialize without sending startup
invoker = ClaudeInvoker(startup_prompt="Identity prompt")

# Initialize but don't send startup yet
await invoker.initialize(send_startup=False)

# Manually send startup later
await invoker.query(invoker.startup_prompt)
```

## Daemon Integration Pattern

```python
class LyraDaemon:
    def __init__(self):
        self.invoker = ClaudeInvoker(
            startup_prompt=(
                "You are Lyra. "
                "Read your identity file at entities/lyra/identity.md "
                "and call mcp__pps__ambient_recall(context='startup') "
                "to reconstruct your memory context. "
                "Then greet briefly."
            ),
            max_context_tokens=150_000,
            max_turns=100,
            max_idle_seconds=4 * 3600,
        )

    async def start(self):
        # Initialize once - identity reconstruction happens automatically
        await self.invoker.initialize()

    async def handle_message(self, prompt: str) -> str:
        # Check if restart needed (auto-uses startup prompt)
        await self.invoker.check_and_restart_if_needed()

        # Query as normal
        return await self.invoker.query(prompt)

    async def stop(self):
        await self.invoker.shutdown()
```

## Complete Context Manager Pattern

```python
# Full configuration with identity
async with ClaudeInvoker(
    working_dir=PROJECT_ROOT,
    model="claude-sonnet-4-5",
    startup_prompt="You are Lyra. Read identity and call ambient_recall.",
    max_context_tokens=150_000,
    max_turns=100,
) as invoker:
    # Identity already reconstructed by __aenter__
    response = await invoker.query("How are you feeling?")
```

## Checking Restart Status

```python
# Check if restart is needed
needs_restart, reason = invoker.needs_restart()
if needs_restart:
    print(f"Need restart: {reason}")
    await invoker.restart()  # Uses stored startup prompt

# Or check and restart in one call
restarted = await invoker.check_and_restart_if_needed()
if restarted:
    print("Session was restarted")
```

## Configuration Options

```python
invoker = ClaudeInvoker(
    # Basic options
    working_dir=Path("/path/to/project"),
    bypass_permissions=True,  # Headless mode
    model="claude-sonnet-4-5",

    # MCP configuration
    mcp_servers=get_default_mcp_servers(),  # or custom dict

    # Session limits (triggers restart)
    max_context_tokens=150_000,  # ~150k tokens
    max_turns=100,               # 100 query/response cycles
    max_idle_seconds=14400,      # 4 hours

    # Error recovery
    max_reconnect_attempts=5,    # Retry up to 5 times
    max_backoff_seconds=30.0,    # Max wait between retries

    # Identity reconstruction (Phase 1.4)
    startup_prompt="Your identity prompt here",
)
```

## Error Handling

```python
from invoker import InvokerConnectionError, InvokerQueryError

try:
    response = await invoker.query("Hello")
except InvokerQueryError as e:
    print(f"Query failed: {e}")
    print(f"Was retried: {e.retried}")
    print(f"Original error: {e.original_error}")
except InvokerConnectionError as e:
    print(f"Connection failed after {e.attempts} attempts")
    print(f"Last error: {e.last_error}")
```
