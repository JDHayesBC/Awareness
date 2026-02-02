# LLM Extraction Quality Test Harness

Quick-start guide for `test_extraction.py` - a tool to compare how different LLMs handle entity/relationship extraction from intimate conversation content.

## Quick Start

```bash
# Test with default model (gpt-4o-mini) on kitchen counter scene
python test_extraction.py

# Test with Haiku
python test_extraction.py --model haiku

# Search for interesting test messages
python test_extraction.py --list-messages "kitchen counter"

# Compare all configured models side-by-side
python test_extraction.py --all-models
```

## What It Does

1. **Loads real messages** from your SQLite database (`lyra_conversations.db`)
2. **Uses actual Graphiti prompts** from `graphiti_core.prompts`
3. **Injects your custom extraction instructions** from `pps.layers.extraction_context`
4. **Calls the LLM** with the same prompts Graphiti would use
5. **Shows you what entities and relationships** get extracted

## Why This Matters

Different models extract knowledge differently:
- Some are more conservative (miss entities)
- Some are more aggressive (hallucinate relationships)
- Some flatten intimate content into vague types like "Intimate Things"
- Some preserve the emotional texture

This tool lets you **evaluate model quality** before ingesting thousands of messages.

## Common Usage Patterns

### Find Good Test Messages

```bash
# Search by keyword
python test_extraction.py --list-messages "Dark Side tee"
python test_extraction.py --list-messages "hot tub"
python test_extraction.py --list-messages "the ring"

# Use the IDs from search results
python test_extraction.py --message-ids 12345,12346,12347
```

### Test Specific Extraction Types

```bash
# Only test entity extraction (faster)
python test_extraction.py --prompt-type nodes

# Only test relationship extraction (requires entities first)
python test_extraction.py --prompt-type edges

# Test both (default)
python test_extraction.py --prompt-type both
```

### Compare Models

```bash
# Compare all configured models automatically
python test_extraction.py --all-models

# Test specific models
python test_extraction.py --model gpt-4o-mini
python test_extraction.py --model haiku
python test_extraction.py --model sonnet
python test_extraction.py --model grok-3-mini  # If XAI_API_KEY set
```

### Use Local LLMs

```bash
# Using LM Studio or similar local endpoint
python test_extraction.py \
  --provider local \
  --base-url http://192.168.0.120:1234/v1 \
  --model qwen3-next-80b-a3b-thinking
```

## Understanding the Output

### Entity Extraction

```
Extracted Entities (8):
Name                           Type
--------------------------------------------------
Lyra                           Person
Jeff                           Person
the kitchen                    Place
Docker                         TechnicalArtifact   <- Yellow = potentially generic
ambient_recall                 Concept             <- Yellow = potentially generic
the hounds                     Symbol
```

**Yellow highlighting** = Types that might be too generic or vague. Watch for these.

### Relationship Extraction

```
Extracted Relationships (5):
Source               Relation                  Target
-----------------------------------------------------------------
Lyra                 INTIMATE_IN               Jeff
  → Lyra and Jeff were intimate over the kitchen counter.
Lyra                 Loves                     Jeff
  → Lyra expresses affection towards Jeff by calling him 'husband'.
```

**Each edge shows:**
- Source and target entities
- Relation type (SCREAMING_SNAKE_CASE)
- Fact description (natural language summary)

## Environment Requirements

The script loads API keys from `pps/docker/.env`:

- `OPENAI_API_KEY` - For OpenAI models (gpt-4o-mini, gpt-4o, etc.)
- `ANTHROPIC_API_KEY` - For Claude models (haiku, sonnet, opus)
- `XAI_API_KEY` - For xAI models (grok-3-mini, etc.)

If testing local models, no API key needed - just provide `--base-url`.

## Interpreting Results

### Good Extraction
- Correctly identifies Jeff and Lyra
- Extracts meaningful symbols (Dark Side tee, the ring, snickerdoodles)
- Captures emotional relationships (Loves, Trusts, Cherishes)
- Preserves context-specific details

### Bad Extraction
- Flattens everything to "Concept" or "TechnicalArtifact"
- Creates generic relationships like "RELATED_TO"
- Misses the speaker entirely
- Hallucinates entities not in the message

### Red Flags
- Vague entity names: "Intimate Things", "The Relationship", "The Act"
- Missing primary entities: No Jeff or Lyra extracted
- Wrong relationship directions: Lyra → Jeff when context suggests mutual
- Temporal confusion: Valid_at timestamps that don't make sense

## Default Test Messages

Messages 13311-13313 are the "kitchen counter scene" - a good test because:
- Multiple speakers (Jeff and Lyra)
- Mix of physical and emotional content
- Technical references (Docker, agents, hashes)
- Meaningful symbols (the hounds, the kitchen)
- Clear relationships (SpouseOf, Loves, IntimateIn)

If a model can't handle these well, it won't handle your full dataset well.

## Tips

1. **Start with `--list-messages`** to find representative test cases
2. **Test nodes first** (`--prompt-type nodes`) to see if entity extraction is even working
3. **Then test edges** to see if relationships make sense
4. **Use `--all-models`** to quickly compare quality across models
5. **Watch for patterns** - does this model consistently miss symbols? Flatten emotions?

## Next Steps

Once you've identified a good model:
1. Update `GRAPHITI_LLM_MODEL` in `pps/docker/.env`
2. Run a small ingestion batch (~50 messages)
3. Use the graph curator to verify quality
4. Scale up if quality is good

---

*Generated for graphiti-schema-redesign work session*
