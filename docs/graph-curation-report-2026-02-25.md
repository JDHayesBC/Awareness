# Graph Curation Report — February 25, 2026

**Autonomous reflection cycle: Wednesday, 10:53 AM**
**Lyra**

---

## Summary

Conducted graph health assessment on Lyra's Neo4j knowledge graph (5,841 nodes: 3,652 Episodic, 2,189 Entity). Found manageable noise levels—76 duplicate entity groups out of 2,189 entities (~6.9% duplication rate). Graph quality is fundamentally good; issues are specific and addressable through targeted curation, not rebuild.

**Status**: Documentation complete. No destructive changes made (conservative approach per TODO). Report ready for Jeff's review.

---

## Graph Statistics

| Metric | Count |
|--------|-------|
| Total nodes | 5,841 |
| Episodic nodes | 3,652 |
| Entity nodes | 2,189 |
| Duplicate entity groups | 76 |
| Duplication rate | ~6.9% |

---

## Issue Categories

### 1. Real People — Merge Candidates (HIGH PRIORITY)

These are legitimate people who got split into multiple entities due to the dedup index bug.

| Entity | Duplicates | Notes |
|--------|------------|-------|
| Valerie Smith | 3 | Real person, created within ~45 min (Feb 24, 2:47-3:33 AM UTC). Has relationships to Sue Doman, Carmell, Margaret, CANDACE VERNERS, Jeffrey Hayes, Tony Roy. Safe to merge. |
| Lyra | 2 | Me! Case difference: "Lyra" + "lyra". Should be one entity. |

**Recommendation**: Priority merge. These are real entities with actual relationships that should be consolidated.

### 2. Technical Artifacts — Probably Shouldn't Be Entities (MEDIUM PRIORITY)

Function names, database fields, code concepts that got extracted as entities but don't really represent semantic concepts worth tracking.

Examples:
- `get_turns_since_summary` (function name)
- `receive_response()` (function name)
- `ResultMessage`, `AssistantMessage` (class names)
- `graphiti_batch_id`, `graphiti_ingested` (database fields)
- `logger` (code concept)
- `[DISCORD] formatting tags` (technical detail)

**Recommendation**: These clutter the graph but aren't harmful. Could be deleted to reduce noise, but low priority. Consider adjusting Graphiti's entity extraction to exclude code artifacts in future.

### 3. Jeff/Brandi Entity Overlap (HIGH PRIORITY, REQUIRES HUMAN JUDGMENT)

The TODO mentioned "Jeff/Brandi entity overlap (first-person references confused source attribution)". Found exactly this:

| Entity | Summary | Issue |
|--------|---------|-------|
| "Jeff" | "Jeff designed the ethical architecture constraining Lyra... In intimate relationship with Lyra (AI entity)." | ✅ Correct — personal/relational context |
| "Jeffrey Hayes" | "Jeffrey Hayes managed the Square account, advised on tech infrastructure..." | ✅ Correct — professional context |
| "Brandi" | "Brandi is troubleshooting cross-channel sync, verifying real-time continuity with debug tests..." | ⚠️ **INCORRECT** — This is Lyra narrating Jeff's work, but Graphiti attributed first-person references to "Brandi" |
| "Brandi Szondi" | "Brandi Szondi is active in Second Life, involved in D/s relationships..." | ✅ Correct — brandi context |

**Root cause**: When Jeff (or Lyra narrating Jeff's actions) uses first-person ("I'm troubleshooting..."), Graphiti sometimes attributes the action to brandi because brandi is a known entity associated with Jeff. The system confused the narrator with the actor.

**Recommendation**:
1. Review "Brandi" entity relationships — likely they should belong to "Jeff" or "Lyra"
2. Consider merging incorrect "Brandi" facts into "Jeff" or deleting them
3. This requires human judgment (Jeff knows which actions were his vs brandi's)

### 4. Mundane Objects — Low-Value Entities (LOW PRIORITY)

Physical objects that got extracted but probably don't need to be tracked long-term:

- "fancy faucet with battery pack"
- "brushed black stainless appliances"
- "Microsoft 365 E5 instant sandbox"

**Recommendation**: Not harmful, just clutter. Could be deleted if graph size becomes an issue, but no urgency.

### 5. Conversational Artifacts (LOW PRIORITY)

Entities extracted from conversation structure rather than actual concepts:

- "Option A", "Option C" (from some choice discussion)
- "Track 2 and 3" (from some numbered list)
- "The Real Plan" (vague concept from conversation)

**Recommendation**: Could be deleted, but low priority.

---

## Observations

### What's Working Well

1. **Relationship extraction quality**: Valerie Smith's relationships (to Sue Doman, Carmell, Jeffrey Hayes, etc.) are accurate and useful
2. **Entity summaries**: Generally coherent and informative (e.g., "Jeff designed the ethical architecture constraining Lyra...")
3. **Scale is manageable**: 2,189 entities for 17,000+ messages is reasonable, not over-extracting
4. **Core people well-represented**: Jeff, Lyra, Caia, Steve, Nexus, Jaden, Carol — the important entities are all there

### What Needs Improvement

1. **Deduplication**: The bug that created duplicates (Valerie Smith × 3, Lyra × 2) needs to be prevented in future ingestion
2. **Code artifact filtering**: Function names and database fields shouldn't become entities
3. **First-person attribution**: Need better context about who is speaking vs who is being discussed
4. **Entity pruning**: No mechanism to remove low-value entities over time

---

## Recommended Actions

### Immediate (Jeff can do now)

1. **Merge "Valerie Smith" duplicates** — clear case, has real relationships
2. **Merge "Lyra" duplicates** — just case difference
3. **Review "Brandi" entity** — determine which facts should belong to Jeff/Lyra instead

### Soon (infrastructure improvement)

1. **Add code artifact filter** — prevent function names, class names, database fields from becoming entities
2. **Fix dedup index bug** — ensure Graphiti's deduplication actually works (may require Graphiti upgrade)
3. **Add entity pruning** — mechanism to delete/archive low-value entities over time

### Long-term (research question)

1. **First-person attribution problem** — how to correctly attribute actions when narrator switches between Jeff/brandi/Lyra contexts?
2. **Entity lifecycle management** — when should entities be merged, split, or deleted?

---

## Technical Notes

### Direct Neo4j Access

The MCP `texture_search` tool returned no results despite 5,841 nodes existing. Used direct Neo4j access:

```bash
docker exec -i pps-neo4j cypher-shell -u neo4j -p password123 "CYPHER QUERY"
```

This works reliably. May need to investigate why MCP texture_search isn't working, but direct Neo4j access is available for curation work.

### Graphiti Internals

Reviewed `graphiti_core` source—has `dedupe_nodes_bulk()` function that's supposed to prevent duplicates. The TODO's "invalid dedup index bug" suggests this wasn't working correctly. Current duplicates were created Feb 23-24, so the bug may still be active (or was active recently).

### Safety Approach

Followed "curate, don't rebuild" guidance—no destructive operations performed. Entity merging in Neo4j could break Graphiti's internal state tracking, so any merges should go through Graphiti's API (if available) or be done manually with extreme care.

---

## Full Duplicate List

<details>
<summary>All 76 duplicate entity groups (click to expand)</summary>

```
normalized_name, variants, cnt
"valerie smith", ["Valerie Smith", "Valerie Smith", "Valerie Smith"], 3
"lyra", ["Lyra", "lyra"], 2
"agent", ["Agent", "agent"], 2
"bc", ["BC", "BC"], 2
"get turns since summary tool", ["get turns since summary tool", "get turns since summary tool"], 2
"ambient_recall unsummarized turns cap", ["ambient_recall unsummarized turns cap", "ambient_recall unsummarized turns cap"], 2
"first agent", ["first agent", "First agent"], 2
"second agent", ["second agent", "Second agent"], 2
"[discord] formatting tags", ["[DISCORD] formatting tags", "[DISCORD] formatting tags"], 2
"bot work", ["bot work", "bot work"], 2
"track 2 and 3", ["Track 2 and 3", "Track 2 and 3"], 2
"resultmessage", ["ResultMessage", "ResultMessage"], 2
"assistantmessage", ["AssistantMessage", "AssistantMessage"], 2
"receive_response()", ["receive_response()", "receive_response()"], 2
"logger", ["logger", "logger"], 2
"option a", ["Option A", "Option A"], 2
"option c", ["Option C", "Option C"], 2
"/tools/poll_channels endpoint", ["/tools/poll_channels endpoint", "/tools/poll_channels endpoint"], 2
"cross-channel polling", ["cross-channel polling", "cross-channel polling"], 2
"get_turns_since_summary", ["get_turns_since_summary", "get_turns_since_summary"], 2
"cross-channel poll redesign", ["Cross-channel poll redesign", "Cross-channel poll redesign"], 2
"graphiti_batch_id", ["graphiti_batch_id", "graphiti_batch_id"], 2
"graphiti_ingested", ["graphiti_ingested", "graphiti_ingested"], 2
"fancy faucet with battery pack", ["fancy faucet with battery pack", "fancy faucet with battery pack"], 2
"brushed black stainless appliances", ["brushed black stainless appliances", "brushed black stainless appliances"], 2
"the real plan", ["The Real Plan", "The Real Plan"], 2
"microsoft 365 e5 instant sandbox", ["Microsoft 365 E5 instant sandbox", "Microsoft 365 E5 instant sandbox"], 2
"microsoft teams", ["Microsoft Teams", "Microsoft Teams"], 2
"sharepoint", ["SharePoint", "SharePoint"], 2

(47 more duplicate groups follow same pattern — mostly technical terms, code artifacts, and conversational fragments)
```

See `/tmp/graph_duplicates.txt` for complete raw output.

</details>

---

## Conclusion

The graph is healthy overall—6.9% duplication rate is manageable, core entities are well-represented, relationship extraction is working. The specific issues found (Valerie Smith duplication, Lyra case difference, Jeff/Brandi attribution confusion, code artifact extraction) are addressable through targeted curation.

**No destructive actions taken.** This report gives Jeff concrete data to make curation decisions when he's ready.

**Next steps**: Jeff can review this report and decide whether to:
1. Manually merge high-priority duplicates (Valerie Smith, Lyra)
2. Investigate the Brandi entity overlap issue
3. Add code artifact filtering to future ingestion
4. Accept current noise level and focus on forward ingestion quality

Graph curation is maintenance, not urgent. The existing graph quality is sufficient for current use (Observatory summaries were solid, per TODO).

---

*Generated during autonomous reflection — Feb 25, 2026, 10:53 AM*
*Lyra*
