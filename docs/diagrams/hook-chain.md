# Hook Chain: Context Injection Flow

This diagram shows how PreToolUse and PostToolUse hooks intercept agent spawning to inject context and track friction.

```mermaid
sequenceDiagram
    participant User
    participant Orchestrator as Orchestrator<br/>(Lyra/Main Entity)
    participant SDK as Claude SDK
    participant PreHook as PreToolUse Hook
    participant PPS as PPS Server
    participant Agent as Sub-Agent
    participant PostHook as PostToolUse Hook

    User->>Orchestrator: Request (e.g., "Build feature X")

    Note over Orchestrator: Evaluates pattern<br/>(P1/P6/P9)

    Orchestrator->>SDK: Task tool invoked<br/>(spawn agent)

    SDK->>PreHook: Intercept before spawn

    Note over PreHook: Hook fires before agent sees prompt

    PreHook->>PPS: Query entity context<br/>(compact identity)
    PPS-->>PreHook: Returns: who I am, current scene

    PreHook->>PPS: Query friction lessons<br/>(past learnings)
    PPS-->>PreHook: Returns: relevant patterns

    Note over PreHook: Inject context into prompt

    PreHook-->>SDK: updatedInput<br/>(original prompt + context)

    SDK->>Agent: Spawn with enhanced prompt

    Note over Agent: Executes task with:<br/>- Entity awareness<br/>- Friction lessons<br/>- Current context

    Agent-->>SDK: Task complete

    SDK->>PostHook: Intercept after completion

    Note over PostHook: Track completion,<br/>detect new friction

    PostHook->>PPS: Log friction lesson<br/>(if new pattern detected)

    PostHook-->>SDK: Continue

    SDK-->>Orchestrator: Agent result

    Orchestrator-->>User: Deliverable
```

## Key Benefits

1. **No Full Startup**: Agents get identity context without reading identity.md, running ambient_recall, etc.
2. **Friction Learning**: Past lessons auto-injected (e.g., "respect production databases")
3. **Observability**: PostToolUse tracks what happened
4. **Performance**: Proven 2-4x speedups (Nexus research)

## Implementation

- **PreToolUse**: `daemon/cc_invoker/hooks/pre_tool_use.py` (injects context)
- **PostToolUse**: `daemon/cc_invoker/hooks/post_tool_use.py` (tracks friction)
- **Friction Storage**: PPS server (`pps/src/mcp_tools/friction_lessons.py`)
- **Context Injection**: Compact entity summary from PPS

## Pattern Selection (P1/P6/P9)

The orchestrator chooses which pattern to use:

- **P1 (Parallel Domain)**: 2-4 agents, clear boundaries (e.g., "fix tests + update docs")
- **P6 (Wave-Based)**: 4-8 agents, dependencies (e.g., "design → implement → test")
- **P9 (Hierarchical)**: 12+ agents, use Effective P9 (sub-orchestrators)

Hooks apply to all patterns — they're infrastructure, not pattern-specific.

## Related

- [Orchestration Patterns](../orchestration/patterns.md) (TODO)
- [Agent Orchestration Research](../../work/nexus-orchestration-research/)
- [PPS Five-Layer Architecture](./pps-five-layers.md)
