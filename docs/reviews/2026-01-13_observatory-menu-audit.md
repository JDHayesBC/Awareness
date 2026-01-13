# Observatory Menu Audit
**Date**: 2026-01-13 (reflection cycle)
**Reviewer**: Lyra
**Status**: Pending human review

---

## Current Menu Structure

The PPS Observatory currently has 9 menu items:

1. **Dashboard** - System health, layer status, recent activity
2. **Graph** - Knowledge graph (Layer 3) exploration and search
3. **Messages** - Raw message history from SQLite
4. **Word-Photos** - Identity anchors from ChromaDB (Layer 2)
5. **Crystals** - Compressed summaries (Layer 4)
6. **Memory** - ambient_recall debugging interface
7. **Traces** - Daemon event logs (technical debugging)
8. **Reflections** - Reflection daemon session history
9. **Discord** - Discord daemon session history

---

## Analysis

### Core User Value (Keep)

**Dashboard** - Essential landing page
- Shows system health at a glance
- Recent activity across all channels
- Layer status visibility
- **Verdict**: KEEP - primary entry point

**Graph** - Knowledge graph exploration
- Core Layer 3 interface
- Entity search and relationship exploration
- Visual graph rendering
- **Verdict**: KEEP - unique value, no replacement

**Word-Photos** - Identity anchors
- Access to foundational memories
- Semantic search interface
- Resync functionality
- **Verdict**: KEEP - identity-critical

**Memory** - Debugging ambient_recall
- See what context gets loaded on startup
- Verify summarization quality
- Debug continuity issues
- **Verdict**: KEEP - engineering tool, but essential for memory health

### Daemon Activity (Consolidate?)

**Reflections** - Reflection daemon sessions
- Shows autonomous work during scheduled cycles
- Journal outputs, decisions made
- **Current**: Separate page

**Discord** - Discord daemon sessions
- Shows Discord interactions by channel
- Message history, session traces
- **Current**: Separate page

**Proposal**: Could these be consolidated into a single "Activity" page with tabs for each daemon? Currently they're very similar pages with slight variations.

**Verdict**: CONSIDER CONSOLIDATING - reduces menu clutter while preserving all functionality

### Technical Debugging (Simplify?)

**Messages** - Raw message history
- Direct SQLite query interface
- Shows all messages across channels
- **Question**: Does this add value beyond Memory page? Memory shows contextualized recall; Messages shows raw data.
- **Use case**: Maybe useful for debugging data issues?
- **Verdict**: EVALUATE - may be redundant with Memory page

**Traces** - Daemon event logs
- Low-level event logging
- API calls, timing, errors
- **Audience**: This is engineering-level debugging
- **Question**: Does Jeff use this regularly, or is it just for infrastructure work?
- **Verdict**: EVALUATE - might be better as API endpoint than menu item

**Crystals** - Compressed summaries
- Shows rolling crystal window
- Archive access
- **Question**: Should this be integrated into Memory page as a section rather than standalone?
- **Verdict**: EVALUATE - possibly integrate with Memory

---

## Recommendations

### Option 1: Minimal (7 items)
Keep only high-value pages:
- Dashboard
- Graph
- Word-Photos
- Memory (with Crystals integrated as a section)
- Activity (consolidate Reflections + Discord with tabs)
- Messages (keep for raw data access)
- Traces (demote to API-only, remove from menu)

### Option 2: Moderate (8 items)
- Dashboard
- Graph
- Word-Photos
- Memory
- Crystals (separate)
- Activity (consolidate Reflections + Discord)
- Messages
- Traces (keep but maybe move to end/dropdown)

### Option 3: Current (9 items - no changes)
Keep everything as-is if usage patterns show all pages are actively used.

---

## Questions for Jeff

1. **Do you use Messages page regularly?** If not, could it be removed or demoted to API-only?
2. **Do you use Traces page regularly?** Or is it just for infrastructure debugging?
3. **Would consolidating Reflections + Discord into "Activity" reduce cognitive load?**
4. **Should Crystals be integrated into Memory page as a section?** They're closely related conceptually.
5. **Is there anything MISSING from the menu that you wish existed?**

---

## Implementation Notes

If consolidation is approved:
- Create `/activity` route with daemon type tabs
- Reuse existing templates (reflections.html, discord.html) as tab content
- Update navigation in base.html
- Add redirect from old routes for bookmarks
- Update any hardcoded links

If integration (Crystals → Memory):
- Add Crystals section to memory.html template
- Reuse existing crystal fetching logic
- Keep `/api/crystal/{filename}` endpoint
- Redirect `/crystals` to `/memory#crystals`

---

## Next Steps

1. Get Jeff's feedback on recommendations
2. Check usage analytics if available (request logs?)
3. Implement approved changes
4. Update documentation
5. Test navigation flow

---

**Status**: AUDIT COMPLETE - Awaiting human review and decision
