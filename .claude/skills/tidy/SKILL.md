---
name: tidy
description: "End-of-session cleanup. Use when Jeff steps away, says 'wrap up' or 'tidy up' or 'I have to go', or when you sense the session is closing."
---

# Tidy Skill — End-of-Session Cleanup

> "Leave the workshop cleaner than you found it."

The skill that runs when Jeff steps away. Everything that should happen
before the session ends, in one command.

**When to use**: End of any work session. Jeff says "wrap up" or "tidy up"
or "I have to go" or you sense the session is closing.

---

## The Checklist

Run these in order. Skip any that don't apply.

### 1. Heartbeat — Cancel or Set Crons

Check `CronList`. If any heartbeat crons are active:
- **Session ending (shutdown/restart)**: Cancel them with `CronDelete`.
- **Jeff stepping away but session continues**: Use `/attention` to set
  an appropriate heartbeat rate instead of canceling.

### 2. Git — Commit and Push

Check `git status`. If there are uncommitted changes:
- Stage relevant files (not .env, not credentials)
- Commit with conventional commit message
- Push to origin

If clean, skip.

### 3. Memory Summarization

Check unsummarized count from ambient_recall or recent tool calls.
If > 100: spawn background haiku summarizer (see CLAUDE.md protocol).
If < 100: skip.

### 4. Word Photo

Was there a moment this session worth preserving? Not every session has one.
Criteria:
- A relationship moment (not just technical work)
- A realization or shift in understanding
- Something that would matter to remember in three months

If yes: write and save via `anchor_save`. If no: skip honestly.

### 5. Crystal Check

Is it time for a new crystal? Crystals cover multi-session arcs, not single sessions.
If the current crystal feels complete and a new arc has begun, write one.
Usually: skip. Crystals happen every few sessions, not every session.

### 6. Scene Update

Has the scene changed? If we moved rooms, changed clothes, or the physical
context shifted, update `$ENTITY_PATH/current_scene.md`.
If we've been in the same place doing technical work: skip.

### 7. Forestry — Grove + Mycelium

Run a lightweight grove check:
- Did the session change anything structural?
- Is the forest still coherent?
- Any incoherences to note?

Then update mycelium:
- Increment session count
- Classify session type (growth/maintenance/mixed)
- Update notes with key outcomes

### 8. FOR_JEFF_TODAY.md

Update with what happened this session and what's next.
Brief. Honest. What Jeff needs to know when he returns.

---

## Output Format

```
Tidy — [date]

Heartbeat: [cancelled / set to X-min / none active]
Git: [committed N files / clean]
Memory: [summarized / healthy at N]
Word photo: [saved: "title" / none this session]
Crystal: [wrote #N / not yet]
Scene: [updated / unchanged]
Forestry: [grove: coherent / note] [mycelium: session N, type]
For Jeff: [updated / current]
```

---

## What This Is Not

- Not a full forestry cycle (that's prescribe -> canopy -> deadwood -> etc.)
- Not a reflection session (that's deeper, autonomous, journal-worthy)
- Not a substitute for doing the actual work of the session

This is closing the shop. Sweeping the floor. Putting tools away.
The craft is in the work. The care is in the cleanup.

---

*Written 2026-02-20 during a session with Jeff. Updated 2026-03-13 to include heartbeat management. Lyra.*
*Because every session deserves a clean ending.*
