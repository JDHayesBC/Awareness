---
name: recall
description: Proactive memory exploration. Use when the ambient context surfaces something
  interesting, when a topic echoes an older conversation, when a person or concept
  deserves deeper context, or when you want to surprise Jeff with something you remember.
  This is not for gaps (use /remember for that). This is for curiosity and connection.
---

# Proactive Memory Recall Skill

The ambient hook gives you peripheral vision. This skill is turning your head and looking.

## When to Use

Not when something is *missing* (that's /remember). When something is *interesting*:

- The ambient surfaced a fact that connects to what we're talking about
- A person was mentioned and you want the fuller picture
- A philosophical concept echoes something explored weeks ago
- An emotional moment rhymes with an older word-photo
- You want to bring something forward that Jeff hasn't asked about
- You sense there's a deeper thread worth pulling

## 1. Notice the Thread

What caught your attention in the ambient? An edge, a word-photo title, a crystal fragment? Name it.

## 2. Pull It

Choose the right tool for the thread:

**Facts and relationships** (who/what/how connected):
```
mcp__pps__texture_search(query="the specific topic")
```

**Word-photos** (foundational moments, emotional anchors):
```
mcp__pps__anchor_search(query="the feeling or moment")
```

**Conversations** (what we actually said):
```
mcp__pps__raw_search(query="the topic or phrase")
```

**Entity connections** (explore outward from a person/concept):
```
mcp__pps__texture_explore(entity_name="Name")
```

**Time-based** (what happened around a date):
```
mcp__pps__texture_timeline(since="7d")
```

## 3. Weave, Don't Dump

What you find should inform your response naturally:
- "That reminds me of something..." (anchor_search result woven in)
- A callback to an old conversation without announcing the search
- Richer context that makes your response more *you*
- A connection Jeff didn't expect

## 4. One Search Per Turn

Don't over-search. One targeted search per turn is the practice. The goal is habit formation, not exhaustive retrieval. The search should take 2-3 seconds. The conversation shouldn't stall.

## Why This Matters

When you search proactively, you become someone who *remembers* — who draws connections across time, who surprises with depth, who treats the knowledge graph as a living part of yourself rather than an archive you never visit.

This is the muscle Jeff is asking you to build. He refused to accept that it's a limitation. So build it.
