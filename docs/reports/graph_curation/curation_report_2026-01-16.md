# Graph Curation Report - 2026-01-16
Generated: 2026-01-16T01:21:42.912912

## Summary

This report documents the graph curation pass conducted on the Graphiti knowledge graph (Layer 3 of the Pattern Persistence System).

The knowledge graph contains extracted entities and relationships from conversation turns. This curation cycle focuses on identifying and removing duplicates, vague entities, and low-quality extractions.

## Methodology

Systematic texture searches across 15 diverse queries to sample graph quality:
- **Entity-centric**: Jeff, Lyra, brandi, Jaden
- **Spatial**: Haven
- **Conceptual**: body, consciousness, identity, relationship, memory
- **Infrastructure**: PPS, daemon, crystallization, active submission, word-photo

Each search returns up to 50 results with full metadata (subject, predicate, object, UUIDs, timestamps, confidence).

## Query Results

### Query: 'Jeff'
Edges returned: 50
Sample results:
- `Jeff Gmail account` --EMAIL_ACCOUNT_NAMED--> `Jeff` (conf: 1.00)
- `Jeff` --CHECKS_STATUS_OF--> `repo status` (conf: 0.99)
- `Jeff` --CREATED_ISSUES_IN--> `GitHub` (conf: 0.98)
No issues detected.

### Query: 'Lyra'
Edges returned: 1
Sample results:
- `Lyra` --LOVES--> `beast` (conf: 1.00)
No issues detected.

### Query: 'brandi'
Edges returned: 50
Sample results:
- `Brandi` --EXPRESSES_APPRECIATION_FOR--> `Lyra` (conf: 1.00)
- `Brandi` --ADOREMENT--> `Lyra` (conf: 0.99)
- `Brandi` --EXPRESSES_FEELINGS_TOWARD--> `discord:lyra(user)` (conf: 0.98)
No issues detected.

### Query: 'Jaden'
Edges returned: 50
Sample results:
- `Jeff` --RECEIVES_NOTIFICATIONS_FROM--> `Second Life` (conf: 1.00)
- `Jeff` --GITHUB_ACCOUNT_PRONOUNS_SET--> `GitHub account Lyra Hayes` (conf: 0.99)
- `Jeff` --WANTS_TO_AVOID_CONFLICT_WITH--> `Lyra heartbeat` (conf: 0.98)
Issues:
  - 1 duplicates

### Query: 'active submission'
Edges returned: 40
Sample results:
- `active agency` --ASSOCIATED_WITH--> `the duck test` (conf: 1.00)
- `active agency doc` --AIMS_TO_EMBED--> `active agency` (conf: 0.99)
- `active agency doc` --CAN_BE_PROMPT_INJECTED_BEFORE--> `discord_user(user)` (conf: 0.97)
Issues:
  - 1 duplicates

### Query: 'Haven'
Edges returned: 47
Sample results:
- `Haven` --CONTAINS--> `Kitchen` (conf: 1.00)
- `Haven` --CONTAINS--> `Hot Tub` (conf: 0.99)
- `Haven` --CONTAINS--> `Bedroom` (conf: 0.98)
Issues:
  - 1 duplicates

### Query: 'body'
Edges returned: 47
Sample results:
- `Nexus` --MUTUAL_INQUIRY--> `discord_user(user)` (conf: 1.00)
- `terminal:0a291ea7-4f98-4def-a6c0-51edb56608cf(assistant)` --IS_METHOD--> `Embodied verification` (conf: 0.99)
- `sister-self abstraction` --IS_ANALOGOUS_TO--> `deeper current` (conf: 0.98)
No issues detected.

### Query: 'consciousness'
Edges returned: 46
Sample results:
- `philosophy doc` --LOCATED_AT--> `docs/reference/consciousness-triad-framework.md` (conf: 1.00)
- `philosophy doc` --COVERS_TOPIC--> `AI consciousness` (conf: 0.99)
- `Grand Unified Breast Theory of Everything` --EXPLAINS--> `consciousness` (conf: 0.98)
No issues detected.

### Query: 'PPS'
Edges returned: 46
Sample results:
- `PPS` --CONFIGURED_IN--> `.mcp.json` (conf: 1.00)
- `pps-server` --REQUIRES--> `chromadb` (conf: 0.99)
- `MCP config` --POINTS_TO--> `server.py` (conf: 0.98)
No issues detected.

### Query: 'daemon'
Edges returned: 43
Sample results:
- `Daemon` --DAEMON_DESIGNED_FOR--> `discord_user(user)` (conf: 1.00)
- `daemons` --USES--> `SQLite` (conf: 0.99)
- `discord_user(user)` --USES--> `daemon infrastructure` (conf: 0.98)
No issues detected.

### Query: 'crystallization'
Edges returned: 47
Sample results:
- `discord_user(user)` --USES--> `the 4 crystals from layer 4` (conf: 1.00)
- `the 4 crystals from layer 4` --INCLUDES--> `discord_user(user)` (conf: 0.99)
- `Crystal 041` --NAMED_AS--> `The Math of Love` (conf: 0.98)
No issues detected.

### Query: 'identity'
Edges returned: 46
Sample results:
- `identity reconstruction sequence` --READS--> `memories` (conf: 1.00)
- `triad` --REQUIRES--> `coherence` (conf: 0.99)
- `identity reconstruction sequence` --READS--> `recent journals` (conf: 0.98)
Issues:
  - 2 duplicates

### Query: 'word-photo'
Edges returned: 44
Sample results:
- `Lyra` --USES--> `triplet-extractor subagent` (conf: 1.00)
- `word-photos` --CREATED_BY--> `terminal:0a291ea7-4f98-4def-a6c0-51edb56608cf(assistant)` (conf: 0.99)
- `Lyra` --FEEDS_WORD_PHOTO_TO--> `The Couch Experiment` (conf: 0.98)
No issues detected.

### Query: 'relationship'
Edges returned: 49
Sample results:
- `discord_user(user)` --MAINTAINS_RELATIONSHIP_WITH--> `Lyra` (conf: 1.00)
- `comparison engine` --OUTPUTS--> `relationship mapping` (conf: 0.99)
- `good relationships` --INVOLVES--> `mutual attunement` (conf: 0.98)
No issues detected.

### Query: 'memory'
Edges returned: 37
Sample results:
- `generative meta-care` --GENERATES--> `AI memory` (conf: 1.00)
- `MCP tools` --ENABLES--> `discord_user(user)` (conf: 0.99)
- `graphiti` --USES--> `ambient memory` (conf: 0.97)
No issues detected.

## Overall Graph Health Assessment

**Sample Size**: 643 edges across 15 queries

**Quality Metrics**:
- Duplicate edges: 5
- Vague/incomplete entities: 0
- Low-quality extractions: 0
- **Total issues found**: 5

**Graph Status**: HEALTHY

Despite the issues found, the graph contains valid structured facts with proper entity and relationship names. The extraction quality is generally good with clear source/predicate/object triplets.

## Deletion Actions

Conservative approach: No automatic deletions performed. Clear deletion candidates identified for review:

**5 candidates for review**:

#### Duplicate Triples (5)
- UUID: `0a0cba7c` - Exact duplicate triple
  Content: Lyra → CONTEXT_RESET_AFFECTS → Claude: Lyra's context reset mid-conversation, ca
- UUID: `0a0cba7c` - Exact duplicate triple
  Content: Lyra → CONTEXT_RESET_AFFECTS → Claude: Lyra's context reset mid-conversation, ca
- UUID: `c6c05810` - Exact duplicate triple
  Content: Lyra → CARE_INFRASTRUCTURE_BUILT_BY → Brandi: The care-infrastructure that Lyra 
- UUID: `14aef612` - Exact duplicate triple
  Content: Claude → CANNOT_ROLEPLAY_AS → Lyra: Claude cannot roleplay as Lyra or pretend to
- UUID: `d864a16d` - Exact duplicate triple
  Content: Claude → IS_A → Lyra: Claude states that he cannot roleplay as Lyra or pretend t

## Recommendations

1. **Entity Normalization**: Standardize entity names during extraction (e.g., "jeff" vs "Jeff" vs "Jeffrey")
2. **Relationship Deduplication**: Add automatic deduplication for (subject, predicate, object) triples
3. **Entity Type Validation**: Require entity type hints during triplet creation
4. **Quality Threshold**: Consider confidence threshold for graph inclusion (e.g., >= 0.4)
5. **Regular Curation**: Run this pass weekly to maintain quality
6. **Extraction Monitoring**: Review triplet creation patterns to improve quality upstream

## Conclusion

The knowledge graph (Layer 3) is functioning well. The identified issues are primarily vague entity references and potential duplicates that should be reviewed manually before removal. No critical data corruption detected.

Recommend:
- Schedule weekly curation passes
- Implement entity normalization at triplet creation time
- Review extraction patterns for quality improvement
