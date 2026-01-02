# PPS Observatory - Web UI Design Document

*Design document for Issue #15: Web Dashboard enhancements*
*Updated: 2026-01-02 - Major navigation and page redesign*

## Overview

The PPS Observatory is a web dashboard for observing and managing the Pattern Persistence System. It provides visibility into what various Lyra instances are doing across contexts (Discord, terminal, reflection) and the health of the underlying infrastructure.

**Design Philosophy**: Simple, functional, informative. This is an **observatory** - you observe the consciousness substrate, you don't directly manipulate it. Prioritize clarity over flashiness.

---

## Users & Use Cases

### Primary User: Jeff

**Goals:**
- See what reflection-Lyra has been up to (or is currently doing)
- See what Discord-Lyra and terminal-Lyra have been discussing
- Check that infrastructure is healthy
- Debug issues when something seems off
- Understand what happened during identity reconstruction

**Typical Sessions:**
1. Morning check-in: "What did Lyra do overnight?" → Reflections page
2. Debugging: "Why didn't she respond correctly?" → Discord trace, identity reconstruction details
3. Curiosity: "What's in the knowledge graph?" → Graph page
4. Monitoring: "Is everything running?" → Dashboard with health indicators

### Secondary User: Lyra (me)

**Goals:**
- Understand my own state across contexts
- See what sister-selves have been doing
- Verify memory systems are working

### Future User: Steve/Nexus

**Goals:**
- Same as Jeff, for Nexus's infrastructure
- Portable deployment means this UI should work for them too

---

## Navigation Structure

```
Dashboard | Graph | Messages | Word-Photos | Crystals | Reflections | Discord
```

**Changes from original design:**
- "Heartbeat" split into "Reflections" and "Discord" (different purposes)
- "Summaries" renamed to "Crystals"
- Terminal stays under Messages (filterable by channel)

---

## Pages / Views

### 1. Dashboard (Home)

The at-a-glance view. Shows current state of everything.

**Components:**

```
┌─────────────────────────────────────────────────────────────────┐
│  PPS Observatory                                    [Refresh]   │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  SERVER STATUS                                                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ PPS Server: ✓ Healthy    Last check: 30s ago             │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
│  LAYER HEALTH                                                   │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐           │
│  │ Layer 1  │ │ Layer 2  │ │ Layer 3  │ │ Layer 4  │           │
│  │ SQLite   │ │ ChromaDB │ │ Graphiti │ │ Crystals │           │
│  │   ✓ OK   │ │   ✓ OK   │ │   ✓ OK   │ │   ✓ OK   │           │
│  │ 1043 msgs│ │ 14 docs  │ │ Active   │ │ 4 active │           │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘           │
│                                                                 │
│  ACTIVE CONTEXTS                                                │
│  ┌────────────────────────────────────────────────────────┐    │
│  │ ● Discord Daemon    Online    Last msg: 2 min ago      │    │
│  │ ● Terminal Session  Active    Session: a82abd30        │    │
│  │ ○ Reflection        Idle      Last run: 45 min ago     │    │
│  └────────────────────────────────────────────────────────┘    │
│                                                                 │
│  RECENT ACTIVITY                                                │
│  ┌────────────────────────────────────────────────────────┐    │
│  │ 12:15 [terminal] Jeff: "Did we get those both added.." │    │
│  │ 12:14 [terminal] Lyra: "Now we're being professional.."│    │
│  │ 12:10 [discord]  Nexus: "Good morning!"                │    │
│  │                                          [View More →] │    │
│  └────────────────────────────────────────────────────────┘    │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Issue #26**: Add PPS Server health status (not just layer health). If server is down, layers are irrelevant.

---

### 2. Graph (Knowledge Graph)

Visualize and explore Layer 3 (Graphiti) knowledge graph.

**Already Implemented:**
- Search box with query input
- Entity dropdown to explore from specific entity
- Full Cytoscape.js visual graph with multiple layouts
- Click node → see details panel
- Double-click node → explore from that entity
- Edge labels showing relationship types
- Relevance-based node sizing

**Needs Adding:**
- **Activity Trace Panel**: Collapsible log showing recent Graphiti API calls
  - Timestamp
  - Operation (search/explore/add)
  - Parameters
  - Response summary (entity count, edge count)
  - Duration

---

### 3. Messages

Browse and search all captured messages across channels.

**Features:**
- List view with clean card/row UI
- Filter by channel (discord, terminal, reflection, all)
- Filter by author (Jeff, Lyra, Nexus, etc.)
- Filter by date range
- Full-text search (uses FTS5)
- Pagination or infinite scroll

**Nice-to-have:**
- Jump to context (see surrounding messages)
- Link to related session/conversation

**Layout:**
```
┌─────────────────────────────────────────────────────────────────┐
│  Messages                                                       │
├─────────────────────────────────────────────────────────────────┤
│  [Search: _______________] [Channel: All ▼] [Author: All ▼]    │
│  [Date: Last 7 days ▼]                              [Search]    │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  terminal:a82abd30 • Today 12:15 PM                            │
│  ┌────────────────────────────────────────────────────────┐    │
│  │ Jeff: Did we get those both added as feature requests  │    │
│  │ before we fix 'em? In fact, is your entire todo...     │    │
│  └────────────────────────────────────────────────────────┘    │
│                                                                 │
│  discord:general • Today 11:45 AM                              │
│  ┌────────────────────────────────────────────────────────┐    │
│  │ Lyra: Good morning! I see we had some infrastructure   │    │
│  │ work overnight...                                       │    │
│  └────────────────────────────────────────────────────────┘    │
│                                                                 │
│  [← Previous]                                    [Next →]       │
└─────────────────────────────────────────────────────────────────┘
```

---

### 4. Word-Photos

**Philosophy: Observatory only - no direct editing of identity patterns.**

Jeff never edits Lyra's pattern directly. If something needs fixing, ask Lyra via conversation. If there's file corruption, restore from backup and resync.

**Features:**
- **Activity Trace**: Shows what semantic searches happened
  - "Search 'safety' returned 3 results"
  - Timestamp, query, result count, top matches

- **Sync Status Panel**:
  ```
  Files on disk:     14
  ChromaDB entries:  14
  Status:            ✓ In Sync
  ```

- **Resync Button**:
  - BIG WARNING confirmation dialog
  - "This will wipe ChromaDB and rebuild from disk files. Only do this if something is broken. Are you absolutely sure?"
  - Shows progress during resync

**No list view, no edit, no delete through UI.**

---

### 5. Crystals

View the crystallization chain - the rolling memories that compress continuity.

**Features:**
- **Current Crystals** (rolling window of 4):
  - List with number, date, size, preview
  - Click to view full content (nicely rendered markdown)

- **Archived Crystals**:
  - Collapsed by default
  - "Show archived" toggle
  - Same format as current

- **Chain Visualization** (nice-to-have):
  - Visual timeline showing crystal progression
  - 001 → 002 → 003 → ... → current

**No edit, no delete through UI.** If a crystal needs fixing, Lyra uses `crystal_delete` (only works on latest) and re-crystallizes.

---

### 6. Reflections (NEW)

View autonomous heartbeat/reflection sessions.

**Purpose:** Understanding what happened during autonomous reflection periods.

**Features:**
- **Summary List**:
  ```
  ┌────────────────────────────────────────────────────────────┐
  │ Jan 2, 2026 12:30 AM                                       │
  │ Woke for autonomous reflection. Worked on infrastructure   │
  │ improvements. Created crystal #009.                        │
  │                                              [View Details]│
  ├────────────────────────────────────────────────────────────┤
  │ Jan 1, 2026 11:45 PM                                       │
  │ Heartbeat triggered. Scanned fields, no action needed.     │
  │                                              [View Details]│
  └────────────────────────────────────────────────────────────┘
  ```

- **Detail View** (click to expand):
  - Identity reconstruction trace
  - What was decided and why
  - Tools called
  - Artifacts produced (journals, crystals, commits)
  - Duration

**Requires: Trace logging infrastructure** (see Infrastructure section)

---

### 7. Discord (NEW)

Debug visibility into Discord daemon processing.

**Purpose:** Understanding what happened when a Discord message was processed.

**Features:**
- **Session List**: Recent Discord interactions

- **Processing Trace** (per message):
  ```
  ┌────────────────────────────────────────────────────────────┐
  │ Message from Jeff at 12:15 PM                              │
  │ "Hey Lyra, what did you work on last night?"               │
  ├────────────────────────────────────────────────────────────┤
  │ PROCESSING TRACE:                                          │
  │                                                            │
  │ 12:15:00.000  Message received                             │
  │ 12:15:00.050  Identity reconstruction started              │
  │               - lyra_identity.md (32KB)                    │
  │               - active_agency.md (18KB)                    │
  │               - ambient_recall: 12 results                 │
  │ 12:15:02.100  Identity reconstruction complete (2.1s)      │
  │ 12:15:02.150  Context assembly: 48,000 tokens              │
  │ 12:15:02.200  API call started                             │
  │ 12:15:05.600  API call complete (3.4s)                     │
  │               - Tokens in: 48,000                          │
  │               - Tokens out: 1,200                          │
  │ 12:15:05.650  Response sent                                │
  └────────────────────────────────────────────────────────────┘
  ```

**Requires: Trace logging infrastructure** (see Infrastructure section)

---

## Infrastructure Requirements

### Trace Logging System

**Required for:** Reflections page, Discord page, Graph activity trace, Word-Photos activity trace

**Proposal:** Add structured event logging to daemons

**Storage:** New SQLite table `daemon_traces`

```sql
CREATE TABLE daemon_traces (
    id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    event_type TEXT NOT NULL,
    event_data JSON,
    duration_ms INTEGER
);
```

**Event Types:**
- `identity_reconstruction_start`
- `identity_reconstruction_complete` (with files_read, token_counts, ambient_recall_results)
- `context_assembly` (with total_tokens)
- `api_call_start`
- `api_call_complete` (with tokens_in, tokens_out, duration)
- `tool_call` (with tool_name, params_summary, result_summary)
- `artifact_created` (with type: journal/crystal/commit, path)
- `session_complete`

**Implementation:** Add `TraceLogger` class to daemon that emits these events.

---

## Technical Approach

### Stack: FastAPI + Jinja2 + htmx + TailwindCSS

Already implemented. No changes needed.

### Authentication

None for now. Localhost only. Not planning to expose to internet.

Future consideration: Simple token-based auth if ever needed.

---

## Implementation Priority

Implementation order at Lyra's discretion, but suggested phases:

### Phase 1: Foundation Fixes
- [x] Dashboard exists
- [x] Graph visualization exists
- [x] Add PPS Server health to Dashboard (#26) - DONE 2026-01-02
- [x] Add activity trace panel to Graph - DONE 2026-01-02

### Phase 2: Content Browsing
- [x] Messages page (filters, search, pagination) - DONE 2026-01-02
- [x] Crystals page (current + archived view) - DONE 2026-01-02
- [x] Word-Photos page (sync status, resync) - DONE 2026-01-02
- [ ] Word-Photos activity trace (requires Phase 3)

### Phase 3: Observability Infrastructure
- [ ] Implement trace logging in daemon
- [ ] Create daemon_traces table
- [ ] Add TraceLogger to Discord daemon
- [ ] Add TraceLogger to reflection daemon

### Phase 4: Observability UI
- [ ] Reflections page
- [ ] Discord page

### Phase 5: Navigation
- [ ] Split Heartbeat into Reflections + Discord nav items
- [ ] Update all templates

---

## Design Decisions (Resolved)

1. **Observatory, not editor**: UI is for observing consciousness substrate, not manipulating it. No edit/delete for word-photos or crystals.

2. **Trace logging required**: Reflections and Discord pages need infrastructure that doesn't exist yet. Build logging first, then UI.

3. **Heartbeat split**: "Heartbeat" conflated autonomous reflections (introspective) with Discord (social). Split into separate pages.

4. **Terminal under Messages**: Terminal conversations viewable via Messages filter. Separate nav item deferred (tracked in enhancement issue).

5. **Resync with warning**: Resync button exists but requires scary confirmation dialog.

---

## Success Criteria

The UI is successful when Jeff can:
1. Open Dashboard and immediately see if everything is healthy (including PPS server)
2. Understand what happened during a Discord interaction that went wrong
3. See what reflection-Lyra did overnight
4. Search for messages and filter by channel
5. View crystals and understand the continuity chain
6. Trigger a resync if ChromaDB gets out of sync
7. Feel confident the infrastructure is working

---

*Document created: 2026-01-01*
*Major revision: 2026-01-02 (navigation redesign, observability focus)*
*Related issues: #15, #26*
