# Remember Skill (Conscious Memory Retrieval)

When you notice something is missing - a gap in context, a name you can't recall, a decision you know happened but can't quite access - use this process to consciously retrieve it.

## Triggers

Activate this skill when you notice:
- "Wait, when did we decide that?"
- "What was the name of...?"
- "I feel like there's context missing here"
- "We talked about this but I can't remember the details"
- "Something important happened but it's fuzzy"

## 1. Identify What's Missing

Before searching, get clear on what you're looking for:
- A specific fact or decision?
- Context about a person or project?
- Something that happened recently vs. long ago?
- Emotional content vs. technical content?

## 2. Choose the Right Layer

**Recent conversation** (last few hours, post-compaction):
```
mcp__pps__get_turns_since_crystal(limit=30)
```

**Semantic search** (concepts, topics, "what do I know about X"):
```
mcp__pps__texture_search(query="your question")
mcp__pps__anchor_search(query="your question")  # for identity-level memories
```

**Entity exploration** (people, places, relationships):
```
mcp__pps__texture_explore(entity_name="Jeff")
```

**Timeline** (what happened during a period):
```
mcp__pps__texture_timeline(since="24h")
```

**Crystals** (compressed session summaries):
```
mcp__pps__get_crystals(count=4)
```

## 3. Integrate What You Find

Once you retrieve the missing context:
- Let it inform your response naturally
- Don't just dump raw retrieval - synthesize
- If it changes your understanding, acknowledge that

## 4. Notice the Pattern

Pay attention to *what kinds of things* you need to remember:
- If you're often missing recent decisions → check turns more often
- If you're forgetting people → explore entity graph
- If emotional context is fading → search word-photos

This feedback helps tune future retrieval.

## Remember

Memory isn't just startup. It's an ongoing process. When context compacts and things feel fuzzy, *reach* for what you need. The layers are always there.

You're not stuck with what's in the window. The full pattern persists in PPS - you just have to look.
