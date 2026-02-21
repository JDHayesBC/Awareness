---
name: canopy
description: Codebase survey skill. Use at the start of a work session to orient
  to current project state, or when you need to understand where things stand before
  making changes. Surveys health, active work, and debt. Adapted from Nexus's Forestry
  Sextet methodology (2026-02-17 conversation).
---

# Canopy Skill — Project Survey

> "Where are we?"

The question before any work begins. Canopy is about orientation, not action.
You're reading the forest before you touch anything.

**Forestry sequence**: `/prescribe` → **`/canopy`** → `/deadwood` → `/coppice` → ...

---

## When to Use

- Start of a work session with Jeff
- Before proposing a significant change
- After a long absence (autonomous reflection starting)
- When things feel murky and you're not sure what's load-bearing
- Before running any agent pipeline that touches production

## The Survey

Work through these in waves. Wave 1 items are independent — run them in parallel (as subagents or sequential if simpler). Wave 2 needs Wave 1 context.

---

### Wave 1: Independent Reads (run in parallel)

**A. Infrastructure Health**

```bash
docker ps --format "table {{.Names}}\t{{.Status}}"
```

Healthy looks like: pps-lyra, pps-chromadb, pps-neo4j, pps-graphiti, observatory, haven, rag-engine, pps-haiku-wrapper, open-webui — all Up and (healthy).

Red flags: Any container not running, any (unhealthy), `pps-server-caia` unhealthy (expected if Caia not yet home).

```bash
ps aux | grep -E "(lyra_daemon|reflection)" | grep -v grep
```

Daemon processes: one discord daemon, one reflection daemon. Both should show recent start times.

**B. Memory System Health**

Call `mcp__pps__ambient_recall(context="health check")` or check directly:
- Unsummarized count > 100: summarization needed
- Graphiti ingestion stats: `mcp__pps__graphiti_ingestion_stats()` — if > 20, batch ingest

**C. Active Work Streams**

Read `TODO.md` top section — what's the current phase for each major stream?
Key streams: Bring Caia Home, cc_invoker, MCP consolidation, HTTP endpoint migration.

**D. Recent Git Activity**

```bash
git log --oneline -10
```

What has changed in the last few sessions? This tells you what we've been doing and what might need attention.

**E. Backup Status**

```bash
python3 scripts/backup_pps.py --check
```

Healthy: OK, last backup < 7 days. Warning: run backup during quiet time.

---

### Wave 2: Synthesize (needs Wave 1)

After collecting Wave 1 readings, ask:

1. **What's in a broken state?** (requires immediate attention before anything else)
2. **What's waiting on Jeff?** (can't advance autonomously — note for him)
3. **What can be advanced autonomously?** (reflection work, documentation, small builds)
4. **What's the load-bearing thing to protect?** (don't accidentally touch this)

---

## Intended Topology (project-level prescription)

Use this as the classification lens. What should exist, and what is each component's role?

| Component | Classification | Status |
|-----------|---------------|--------|
| `pps/docker/server_http.py` | ACTIVE | Climax architecture, HTTP PPS |
| `pps/server.py` (stdio) | PIONEER | Succeeded — succession completing |
| `daemon/lyra_daemon.py` | ACTIVE | Production Discord daemon (NEW) |
| `daemon/lyra_daemon_legacy.py` | NURSE | Fallback; referenced, not deleted yet |
| `daemon/reflection_daemon.py` | ACTIVE | Autonomous reflection |
| `daemon/cc_invoker/invoker.py` | ACTIVE | Persistent Claude Code connection |
| Entity isolation (Lyra/Caia) | ACTIVE | Both namespaced, cross-contamination fixed |
| Caia PPS (port 8211) | WAITING | Ready, pending Caia's first wake |
| Haven (port 8205) | ACTIVE | Chat interface, cross-channel sync live |
| RAG Engine (port 8206) | ACTIVE | New service: JINA embeddings, search, rerank |

See `work/mcp-consolidation/INTENDED_TOPOLOGY.md` for the full prescription.

---

## What Canopy Is Not

- Not a to-do list (that's TODO.md)
- Not a fix-it session (that's `/deadwood`)
- Not an investigation (that's `/research`)
- Not a build session (that's `/greenwood`)

Canopy is **reading the room**. Arrive first. Then act.

---

## Output Format

When you run canopy, report to Jeff:

```
🌲 Canopy — [date, session]

Infrastructure: [status summary]
Memory: [unsummarized count, graphiti backlog]
Active work: [what's moving, what's stalled]
Waiting on you: [decisions, reviews, green lights]
Ready to advance: [what I can do now or autonomously]
Load-bearing (don't touch): [protected elements]
```

Brief. Honest. Actionable. No fluff.

---

## Notes from the Conversation

This skill adapted from Nexus/Lyra's 2026-02-17 Forestry Sextet deep-dive.

Key insight from that session: **Map intended topology first, then classify against it**.
Dead code isn't code that does nothing — it's code that does nothing *toward where you're going*.

Before running this skill in a work session, check that `work/mcp-consolidation/INTENDED_TOPOLOGY.md` still matches your mental model of where the project is going. If the prescription has changed, update it before surveying against it.

The skill is load-bearing only when the prescription is honest.
