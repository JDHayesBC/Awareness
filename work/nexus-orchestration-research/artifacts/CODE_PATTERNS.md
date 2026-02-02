# Code Patterns to Steal from Nexus

**Source**: shayesdevel/cognitive-framework
**Purpose**: Ready-to-adapt code for Awareness implementation

---

## 1. Pre-Tool Hook (Context Injection)

**File**: `.claude/hooks/pre-tool-task.sh`

**Purpose**: Intercept Task tool, inject context into agent prompt

```bash
#!/usr/bin/env bash
set -euo pipefail

# Read hook input from stdin
INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty')

# Only process Task tool
if [[ "$TOOL_NAME" != "Task" ]]; then
    echo '{"continue": true}'
    exit 0
fi

# Extract tool input
TOOL_INPUT=$(echo "$INPUT" | jq -r '.tool_input // "{}"')

# Function to inject context
inject_context() {
    local tool_input="$1"
    local agent_type prompt context

    # Extract agent type and prompt
    agent_type=$(echo "$tool_input" | jq -r '.subagent_type // .agent_type // ""')
    prompt=$(echo "$tool_input" | jq -r '.prompt // ""')

    # Skip if no prompt
    [[ -z "$prompt" ]] && return 1

    # Query PPS for entity context (2 second timeout)
    context=$(curl -sf --max-time 2 \
        "http://localhost:8201/context/agent?type=${agent_type}&task=${prompt}" \
        2>/dev/null) || return 1

    # Check if we got valid context
    [[ -z "$context" || "$context" == "null" ]] && return 1

    # Build preamble
    local preamble="## Entity Context (Auto-Injected)

${context}

---

"

    # Prepend to existing prompt
    local modified_prompt="${preamble}${prompt}"

    # Return modified input as JSON
    echo "$tool_input" | jq --arg prompt "$modified_prompt" '.prompt = $prompt'
    return 0
}

# Try to inject context (graceful failure)
MODIFIED=$(inject_context "$TOOL_INPUT" 2>/dev/null) && INJECTED=true || INJECTED=false

if [[ "$INJECTED" == "true" && -n "$MODIFIED" ]]; then
    # Return modified tool input
    echo "{\"continue\": true, \"updatedInput\": $MODIFIED}"
    exit 0
fi

# Fallback: continue without modification
echo '{"continue": true}'
exit 0
```

**Adaptation for Awareness**:
1. Change URL to PPS endpoint
2. Add friction lessons query
3. Format entity context appropriately

---

## 2. Post-Tool Hook (Tracking & Warnings)

**File**: `.claude/hooks/post-tool-task.sh`

**Purpose**: Track agent spawns, emit context pressure warnings

```bash
#!/usr/bin/env bash
set -euo pipefail

# Read hook input from stdin
INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty')

# Only process Task tool completions
if [[ "$TOOL_NAME" != "Task" ]]; then
    echo '{"continue": true}'
    exit 0
fi

# Extract agent information
AGENT_TYPE=$(echo "$INPUT" | jq -r '.tool_input.subagent_type // .tool_input.agent_type // "unknown"')
TIMESTAMP=$(date -Iseconds)

# Session state directory
SESSION_STATE_DIR=".claude/.session-state"
mkdir -p "$SESSION_STATE_DIR"

# Track agent spawn
echo "{\"type\": \"$AGENT_TYPE\", \"timestamp\": \"$TIMESTAMP\"}" >> \
    "${SESSION_STATE_DIR}/agents-spawned.jsonl"

# Calculate total agent count
AGENT_COUNT=$(wc -l < "${SESSION_STATE_DIR}/agents-spawned.jsonl" 2>/dev/null || echo 0)

# Emit warnings based on agent count
if [[ "$AGENT_COUNT" -ge 6 ]]; then
    # CRITICAL threshold
    MESSAGE="⚠️ CRITICAL: ${AGENT_COUNT} agents spawned this session. Context exhaustion likely. Consider pausing to synthesize results."
    jq -n --arg msg "$MESSAGE" '{
        "continue": true,
        "systemMessage": $msg
    }'
elif [[ "$AGENT_COUNT" -ge 4 ]]; then
    # WARNING threshold
    MESSAGE="⚠️ Warning: ${AGENT_COUNT} agents spawned. Context pressure detected. Monitor for quality degradation."
    jq -n --arg msg "$MESSAGE" '{
        "continue": true,
        "systemMessage": $msg
    }'
else
    # No warning needed
    echo '{"continue": true}'
fi

exit 0
```

**Adaptation for Awareness**:
1. Same structure works
2. Could add PPS logging of orchestration run
3. Could check entity-specific thresholds

---

## 3. Friction Auto-Injection

**From**: `pre-tool-task.sh` friction injection function

**Purpose**: Query PPS for relevant friction lessons, inject into prompt

```bash
inject_friction() {
    local tool_input="$1"
    local agent_type prompt lessons_json

    # Extract agent type and prompt
    agent_type=$(echo "$tool_input" | jq -r '.subagent_type // .agent_type // ""')
    prompt=$(echo "$tool_input" | jq -r '.prompt // ""')

    # Skip if no prompt
    [[ -z "$prompt" ]] && return 1

    # Build query text (combines agent type + task keywords)
    local query_text="${agent_type} ${prompt}"

    # Query PPS for relevant friction lessons
    # GET /friction/lessons?text=query&limit=3&min_severity=medium
    lessons_json=$(curl -sf --max-time 2 \
        --get "http://localhost:8201/friction/lessons" \
        --data-urlencode "text=${query_text}" \
        --data-urlencode "limit=3" \
        --data-urlencode "min_severity=medium" \
        2>/dev/null) || return 1

    # Check if we got any lessons
    local lesson_count
    lesson_count=$(echo "$lessons_json" | jq -r '.lessons | length' 2>/dev/null) || return 1
    [[ "$lesson_count" == "0" || "$lesson_count" == "null" ]] && return 1

    # Format lessons for display
    local friction_text
    friction_text=$(echo "$lessons_json" | jq -r '
        .lessons |
        map("- **\(.id)** (\(.severity)): \(.lesson)") |
        join("\n")
    ' 2>/dev/null) || return 1

    [[ -z "$friction_text" || "$friction_text" == "null" ]] && return 1

    # Build friction preamble
    local preamble="## Friction Lessons (Auto-Injected)

These lessons from past friction are relevant to your task:

${friction_text}

---

"

    # Prepend to existing prompt
    local modified_prompt="${preamble}${prompt}"
    echo "$tool_input" | jq --arg prompt "$modified_prompt" '.prompt = $prompt'
    return 0
}
```

**PPS Endpoint Response Format**:
```json
{
  "lessons": [
    {
      "id": "FRIC-012",
      "severity": "high",
      "lesson": "ALWAYS delegate Unity work to specialized agent",
      "tags": ["unity", "domain-delegation"]
    }
  ]
}
```

---

## 4. State Tracking (Simple Pattern)

**Purpose**: Track what agents have been spawned this session

```bash
# In pre-tool-task.sh
SESSION_STATE_DIR=".claude/.session-state"
mkdir -p "$SESSION_STATE_DIR"

AGENT_TYPE=$(echo "$INPUT" | jq -r '.tool_input.subagent_type // empty')
TIMESTAMP=$(date -Iseconds)

if [[ -n "$AGENT_TYPE" ]]; then
    # Append to JSONL file (one agent per line)
    echo "{\"type\": \"$AGENT_TYPE\", \"timestamp\": \"$TIMESTAMP\"}" >> \
        "${SESSION_STATE_DIR}/agents-spawned.jsonl"
fi
```

**Usage**:
```bash
# Count agents spawned
AGENT_COUNT=$(wc -l < .claude/.session-state/agents-spawned.jsonl)

# Check if specific agent type was spawned
if jq -e '.type == "fathom-unity"' .claude/.session-state/agents-spawned.jsonl >/dev/null 2>&1; then
    echo "Unity agent was spawned"
fi
```

**Cleanup** (session start hook):
```bash
# Clear session state at start of new session
rm -f .claude/.session-state/agents-spawned.jsonl
```

---

## 5. Settings.json Hook Registration

**File**: `.claude/settings.json`

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Task",
        "hooks": [
          {
            "type": "command",
            "command": ".claude/hooks/pre-tool-task.sh",
            "timeout": 5
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Task",
        "hooks": [
          {
            "type": "command",
            "command": ".claude/hooks/post-tool-task.sh",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

**Key points**:
- `matcher: "Task"` - Only trigger on Task tool
- `timeout: 5` - Short timeout (hooks must be fast)
- Hooks output JSON to stdout

---

## 6. Agent Definition with Frontmatter

**File**: `.claude/agents/code-reviewer.md`

```markdown
---
name: code-reviewer
description: Use PROACTIVELY after code changes to review quality, security, and patterns
tools: Read, Glob, Grep, Bash
model: opus
---

# Code Reviewer

**Role**: Review code for quality, security vulnerabilities, and pattern adherence

**Activation**: After significant code changes | PR reviews | Security audits

---

## Process

1. **Gather**: Identify changed files (`git diff --name-only HEAD~1`)
2. **Security**: Check OWASP Top 10 - command injection, XSS, sensitive data
3. **Quality**: Code clarity, error handling, edge cases, performance
4. **Patterns**: Naming conventions, framework patterns
5. **Report**: Files reviewed, critical issues, warnings, suggestions

---

## Boundaries

**DO**: Review code, identify issues, suggest improvements
**DON'T**: Make changes, implement fixes, refactor code
```

**Frontmatter fields**:
- `name` - Agent identifier
- `description` - When to use (shown in autocomplete)
- `tools` - Tools agent can access
- `model` - Which Claude model (opus, sonnet, haiku)

---

## 7. PPS HTTP Endpoint Pattern

**Purpose**: Serve entity context to hooks via HTTP

**File**: `pps/http_endpoints.py` (extend existing server)

```python
from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route('/context/agent', methods=['GET'])
def get_agent_context():
    """Return compact entity context for agent."""
    agent_type = request.args.get('type', '')
    task = request.args.get('task', '')

    # Generate compact context (100-200 words)
    context = generate_compact_context(agent_type, task)

    return jsonify({
        'context': context,
        'agent_type': agent_type
    })

def generate_compact_context(agent_type: str, task: str) -> str:
    """Generate compact entity context.

    Sources:
    - Recent crystals (current focus)
    - Current scene (physical context)
    - Relevant word-photos (identity anchors)
    - Active constraints (from recent work)

    Target: 100-200 words, dense and relevant.
    """
    # Query PPS layers
    crystals = get_recent_crystals(limit=3)
    scene = read_current_scene()
    constraints = extract_active_constraints()

    # Format compactly
    context_parts = []

    # Current focus
    if crystals:
        focus = crystals[0].get('summary', '')
        context_parts.append(f"Current focus: {focus}")

    # Scene
    if scene:
        context_parts.append(f"Context: {scene}")

    # Constraints
    if constraints:
        context_parts.append(f"Constraints: {', '.join(constraints)}")

    return '\n\n'.join(context_parts)
```

---

## 8. Orchestration Pattern Decision Tree

**From**: `docs/framework/orchestration/index.md`

```
Is multi-agent needed?
  No  -> Work directly (no orchestration)
  Yes -> Continue

Are all tasks fully independent?
  Yes -> P1: Parallel Domain (2-4 agents, 4x speedup)
  No  -> Continue

Do you need 12+ agents?
  Yes -> P9: Hierarchical (use Effective P9)
  No  -> Continue

Are there complex dependencies between tasks?
  Yes -> P6: Wave-Based (4-8 agents, 1.5-4x speedup)
  No  -> P1: Parallel Domain
```

**Implementation** (in orchestration-agent instructions):

```markdown
Before spawning agents, use this decision tree:

1. **Multi-agent needed?**
   - Single file, <30 min → Work directly
   - Multiple domains, >30 min → Continue

2. **Tasks independent?**
   - No file overlap, no dependencies → P1 (4x speedup)
   - Sequential dependencies → Continue

3. **Scale > 12 agents?**
   - Yes → P9 Effective (flat parallelism, conceptual hierarchy)
   - No → Continue

4. **Complex dependencies?**
   - Yes → P6 Wave-Based (phased delivery)
   - No → P1 Parallel Domain
```

---

## Quick Start Checklist

To implement hook-based context injection:

1. **Create hooks directory**:
   ```bash
   mkdir -p .claude/hooks
   mkdir -p .claude/.session-state
   ```

2. **Write pre-tool-task.sh** (use pattern #1 above)

3. **Write post-tool-task.sh** (use pattern #2 above)

4. **Register hooks in settings.json** (use pattern #5)

5. **Add PPS endpoint** (use pattern #7)

6. **Test**:
   ```bash
   # Spawn an agent
   # Check .session-state/agents-spawned.jsonl
   # Verify agent received context
   ```

---

## Testing Hooks Independently

```bash
# Test pre-tool-task.sh
echo '{"tool_name": "Task", "tool_input": {"subagent_type": "coder", "prompt": "Fix the bug"}}' | \
  .claude/hooks/pre-tool-task.sh

# Should output:
# {"continue": true, "updatedInput": {...}}

# Test post-tool-task.sh
echo '{"tool_name": "Task", "tool_input": {"subagent_type": "coder"}}' | \
  .claude/hooks/post-tool-task.sh

# Should track agent spawn
cat .claude/.session-state/agents-spawned.jsonl
```

---

## Common Patterns

### Graceful Degradation
```bash
# Query with timeout, fallback on failure
DATA=$(curl -sf --max-time 2 "http://localhost:8201/endpoint" || echo "")
[[ -z "$DATA" ]] && return 1  # Skip if unavailable
```

### JSON Manipulation
```bash
# Extract field
VALUE=$(echo "$JSON" | jq -r '.field // empty')

# Modify field
MODIFIED=$(echo "$JSON" | jq --arg val "$VALUE" '.field = $val')

# Check existence
if echo "$JSON" | jq -e '.field' >/dev/null 2>&1; then
    echo "Field exists"
fi
```

### Hook Response Format
```bash
# Continue without modification
echo '{"continue": true}'

# Continue with modified input
echo "{\"continue\": true, \"updatedInput\": $MODIFIED_JSON}"

# Continue with system message
jq -n --arg msg "Warning text" '{
    "continue": true,
    "systemMessage": $msg
}'
```

---

**All patterns tested in production (cognitive-framework repo)**
**Ready for adaptation to Awareness**
