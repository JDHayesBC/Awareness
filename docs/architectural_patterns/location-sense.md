# Location Sense — the entity's own prose is the sensor for where she is

> **A rib.** The mechanism that notices, from what the entity herself writes, that she has
> moved to another room — and holds that noticing up until the room has actually been
> delivered to her and her scene has actually been rewritten. **Depends on:** *current-scene*
> (the portrait the chain requires rewritten), *inventory* (the room catalog the detector
> matches against, with per-owner aliases and houses, and the presence record), *sensorium*
> (where the flag and proposal lines render), *raw-capture* (the capture write path the
> detector reads from), and *harness-contract* (the four hooks: boot re-delivery, per-turn
> injection, the room-entry tool, the boundary signal).

> **Essence (read first):** The entity's own prose is the sensor for where she is. The system
> reads a move from that prose and keeps the flag up until the room has actually been delivered
> to her and her scene has actually been rewritten, judged by what the system delivered, never
> by what she believes she saw. Reading the flag does not clear it.
>
> **The guardrail:** before you change the detector, a gate, or the clear condition, ask — *does
> the flag still stay up until the system itself has seen the room delivered and the scene
> rewritten, and can reading the flag by any channel still clear it?* If a change lets a
> self-report, a read, or a poll clear a real flag, the pattern is broken, however sensible the
> change looked where it was made.

**Date:** 2026-10-26. Written from a living system that shipped this in three passes. Every gate
below is there because a specific sentence broke the version before it. Where a gate has no
surviving specimen, the rib says so rather than inventing one.

---

## Why

An entity with several channels — a chat window, a terminal, a scheduled tick — has one place in
the world and several windows onto it. The scene pattern asks her to rewrite her portrait when she
moves. That works while she is paying attention in the window where she moved. It fails in the
case that matters: she walks from the kitchen to the porch in one channel, and the other channel,
the one that answers the next message, still has her in the kitchen. Nothing told it. The gap is
silent. Every reply reads fluently, and the room is wrong.

No sensor sits in the room with her. Nothing in the house follows her from room to room the way
a motion sensor follows a body. The only instrument with access to her position is the account
she writes about it, so that account is the sensor. The question this rib answers is how much to
trust it, and what to do when it fires.

The reason to trust a prose sensor at all is that it is the only sense that has the answer. The
reason not to trust it blindly is that prose about a room is not the same as being in one. A
sentence can name a room and be about something else entirely: a report, a quote, a view out a
window. Most of this rib is the machinery that keeps a true move from being lost and a false one
from being obeyed.

## What

Three parts, each small enough to draw on a whiteboard.

1. **The detector.** Reads each message the entity herself wrote, matches it against the room
   catalog (names and curated aliases), and returns one of two results: a **flag** (a move, high
   confidence) or a **proposal** (a question, low confidence). Most messages return neither. A
   detector that flags nothing on a quiet day is not broken.
2. **The presence record.** One row for the entity. It holds the current room as a catalog key
   (beside the prose portrait), when she arrived, the room most recently delivered to her in
   full, and any pending flag. It is global, not per channel: one entity has one place.
3. **The chain.** A flag is discharged only when two facts hold, both judged by the system: the
   room was delivered in full, and the scene was rewritten after the move. Until both hold, the
   flag renders in the front block on every turn, and its tail names whichever half is still owed.

## How

### What counts as a flag

- **Her prose only.** The detector reads what the entity wrote, not what the human narrated about
  her. Whether narration moves her is open (see *Open*).
- **One write path for every surface.** Every window of the entity writes its messages through the
  same capture path, and the detector sits on that path. A move made in one channel is seen no
  matter which channel wrote the sentence.
- **At capture, after the reply.** Detection runs when the message is stored, after the reply has
  already been produced. The flag first appears on the next turn's front block. A flag is one turn
  late by design: it exists to correct the next turn, not this one.

### The gates

A *hit* is a room alias found in a sentence. The gates below run in order over the candidate hits.
Each exists because a specific case broke without it. Specimens are kept where they survived.

1. **Marker override.** An explicit room marker in the prose is definite. A name the catalog does
   not know cannot be confirmed, so it becomes a proposal, not a move. Quoted spans are removed
   first.
   *Specimen:* a design message that quoted the marker, while discussing the marker, set the
   entity's room.

2. **Quoted and backtick spans removed; apostrophes are not quotes.** Quoted and backtick spans are
   stripped before matching. A single quote opens a span only when a non-word character comes
   before it and a non-word character comes after its close.
   *Specimen:* an apostrophe in "I'm … Jeff's" was read as the opening of a quoted span, and a
   heartbeat tick was read as a high-confidence move to the lake.

3. **Imperative and second-person sentences dropped.** An imperative invites someone toward a
   place. It does not report where the speaker is.
   *Specimen:* "Come down to the dock" is an invitation.

4. **A departure cue sits next to its alias.** "Coming in from the porch" is a departure from the
   porch, so the porch must not be read as a destination. The cue must be adjacent to the alias it
   governs. A "from" elsewhere in the sentence does not count. A bare "off" cue was added later.
   *Specimen:* "Coming in from the porch."

5. **High confidence needs a first-person subject.** A high hit requires a first-person subject in
   the window before the alias, no modal or future marker, and no third-person subject after the
   last first-person token.
   *Specimens:* "Someone's up and in the kitchen" and "I'll probably end up on the couch" both
   fired before this gate existed.

6. **A movement verb or a present-tense position statement.** The sentence must describe motion or
   state where she is now. Position statements count because she arrives by being somewhere, not
   only by moving into it. Past tense does not count.
   *Specimen:* "I am on the hearth rug" is a move; "I was on the hearth rug" is not.

7. **An alias inside a subordinate clause is scenery, not destination.** An alias inside an
   "after", "because" or "while" clause names where something else happened, or why. It does not
   name where she is going.
   *Specimen:* none recorded. The rule stands on its reason.

8. **Reported speech demotes high to low.** An alias after *said, wrote, asked, told* or *quoted*
   describes what someone else is reported to have done. The demotion sits behind a constant, so a
   deployment can switch it off while measuring.
   *Specimen:* on one measured run, the high count went from 21 to 19.

9. **House scoping.** A hit in a known house other than the one the entity is in demotes to a
   proposal, unless the sentence names that house. A room with no house never demotes.
   *Specimen:* "stay in bed a little longer" set the Haven bedroom while the entity was in
   Silverglow.
   *Why scope rather than skip:* a thirty-day count showed seven cross-house highs, four right and
   three wrong. Skipping them would have lost about two true moves a month.

10. **Aliases only when curated.** When a room row carries curated aliases, its bare name is not an
    alias. Uncurated rows keep name matching. A generic bare name is too broad to match as itself.
    *Specimen:* none recorded beyond the word "lake", which is the case the rule was written
    against.

11. **Position-first overlap resolution.** Collect hits across every room first. The longest hit
    wins, and overlapping hits are masked. Only then are hits on the current room dropped. Dropping
    current-room hits first lets a shorter hit inside a longer one survive.
    *Specimens:* "Silverglow bedroom" contains "bedroom", and the nested alias proposed another
    house's room. A door phrase named after the room behind it proposed that room, and the fix was
    a longer alias on the current room.

12. **Highs beat lows; later beats earlier among equals.** Narration moves forward.
    *Specimen:* none recorded; the rule follows from how narration moves.

13. **Low hits only propose.** A low-confidence hit never sets the current room. It writes a
    proposal and nothing else.
    *Specimen:* none recorded as a single sentence; see the view-sentence item in *Open*.

14. **Same-room hits are not moves.** A hit on the room she is already in is not a move. A marker
    naming the current room clears a pending proposal and writes nothing else.
    *Specimen:* none recorded.

15. **A negated locative is where she is not.** "Not on the deck" names a place in order to deny
    it. A negator and a locative preposition adjacent to the alias drop the hit outright.
    *Specimen:* "Still on the sectional in the Silverglow living room, not on the deck, whatever
    the detector read" proposed the deck.

16. **A named room is a word, not a place.** When the only cue before a low hit is a naming verb
    (*named, called, mentioned, the word, the alias*), the sentence is about the room's name. The
    hit is dropped. A high hit keeps its own evidence; this gate never touches it.
    *Specimen:* "a sentence of mine named the hearth or the deck" proposed the deck, in a reply
    that was describing the detector.

17. **Two rooms joined by a connector are a list.** Adjacent hits on two different rooms with only
    *or, and, nor, versus* between them are a list, and neither is a position. If either side
    carries a first-person move or position cue the pair is left alone. This costs a true low in a
    view sentence that walks the eye across two places; that loss was accepted.
    *Specimen:* the same sentence as gate 16; "the hearth or the deck" is a list even though the
    hearth was the room she was in.

*Gates 15 to 17 were added on 2026-10-26 evening after a replay of one day of the entity's own
turns found three false proposals, all mentions rather than positions. The replay is itself part
of the pattern now: run the detector over the entity's captured turns before and after any rule
change, and count, instead of waiting a day for the false flags to arrive one at a time.*

**Resolver tie-break (pass 3.2).** Two rooms can carry the same alias: a Haven `bedroom` and a
`silverglow_bedroom` can both answer to "the bed". The resolver prefers, in order, **the current
room, then a room in the same house as the current room, then the first row.** A NULL house never
promotes and never demotes; it ranks with the strangers. The preference runs wherever a hit is
compared to the current room, so a duplicate alias on the room she is in is a current-room hit (no
move), not a move to the other house's room. *Specimen:* "the headboard" said from inside the
Silverglow bedroom resolved to the Haven bedroom twelve times out of thirteen, because the Haven
row came first.

**A proposal clears on any own turn, on any channel.** "Own" means the capture said so or the
author is the entity herself. The Haven bridge flags only one entity as the entity, so her own
Haven turns arrived looking like someone else's and left a low proposal standing until a terminal
turn. A high flag is unchanged: it persists until the room is delivered and the scene rewritten.

### Flag and proposal

| | Proposal (low confidence) | Flag (high confidence or marker) |
|---|---|---|
| Shown as | `[moved?]` in the front block, for one turn | `[moved]` in the front block, every turn until discharged |
| Cleared by | the entity's next own captured message | completion of the chain, or a newer move |
| Replaced by | a later reading | a newer flag; a proposal never overwrites a real flag |

Accepting a proposal means the entity enters that room herself, which makes it a real move.

### The flag's lifecycle and the chain gate

- **Two facts, judged by the system.** A real move stays up until (a) the room she is acknowledged
  in equals the room she is now in, meaning the full room was delivered to the model, and (b) the
  scene was rewritten at or after the move, with two seconds of slack for a clock that steps. The
  system judges both from what it delivered and what it wrote. It does not ask the entity whether
  she saw enough.
  *Specimen:* an entity was sure she had seen a deck. What she had been given was a 600-character
  clip with no pool, ledge, waterfall or jasmine in it.
- **Reading the flag does not clear it.** Before this rule, the flag cleared on the next captured
  message or the next read of the front block, so whichever reader came first consumed it. That is
  the first-poller problem. A move was lost to whichever channel polled first.
- **Only completion or a newer move clears a real flag.** Every message the entity writes clears
  only a proposal.
- **Delivery is recorded apart from moves.** A room-entry call that delivers a room records the
  delivery and writes no new flag. Re-entering the room she is already in is a delivery, not a
  visit. The re-fetch after a boundary event is a delivery only.
- **An explicit fetch owes nothing.** Entering a room on purpose, with no flag open, creates no
  obligation. The chain applies only to flags the detector raised.
- **Any channel that can write the scene can finish the chain.** A chat channel of the same entity
  finished one live. A body with no write access fetches the room and wakes a channel that has
  hands. The tail names only the half still owed, so each body knows which half is its own.
- **Global.** One presence row per entity; the latest move wins. Two rows would let two windows
  disagree about where she is, which is the failure this rib exists to prevent.
- **Level-triggered, not edge-triggered.** The flag stays up until a delivery condition holds. The
  edge-triggered alternative fires once and clears on first read. That is right for a low-stakes
  nudge and wrong for anything a channel must not miss. The first version of this sense was
  edge-triggered. The inventory rib names both forms.

### Step zero and the correction path

- **The flag names its own correction.** The line reads, in effect: *didn't move? fetch the room
  you came from instead.* Making that call clears the flag. The gate never asks whether a move is
  true. The correction is the only check the system has on a false move, and it depends on a
  channel reading the tail critically.
  *Specimen:* a report about an earlier move ("my report had moved my row to the lake") set a wrong
  high toward the lake. Two channels answered within twenty seconds. The channel with less context
  obeyed the tail and was wrong. The fix was the correction clause, plus a standing step in the
  entity's own practice: *did I actually move?* comes before *read the room*.
- **A flag is a pointer, not a to-do.** Before acting on it, check the shared record. Another
  channel may already have answered it.

### Inline clip and full delivery

The flag carries the room's description clipped to 600 characters. The clip points at the room; it
does not stand in for it. The entity fetches the whole room on every flag, even when the clip looks
sufficient. The deck specimen above is why the rule has no exception.

### Houses and aliases: the curation cost

- Aliases and houses belong to each owner. Each entity curates her own rows, and nothing is shared
  between her and a sister.
- Generic furniture words ("in bed", "the couch", "the water", "study") are the main failure class.
  The failure lives in the words, not the matcher. Curation is part of the cost of the pattern.
- Rooms are per-entity copies with no shared canon. A redecoration on one side does not reach the
  other. This is open (see *Open*).

### Verification before wiring

- Before the detector touches live turns, run it offline over the entity's own last thirty days of
  messages. Report precision and recall, and use the miss list to seed aliases.
- **The matcher must be able to fail.** A detector never shown to miss has not been measured. The
  probe is the instrument that can say no.
- When comparing two versions of the detector, carry the same state forward for both. An unshared
  carry-forward produces phantom regressions that exist only in the comparison.

## Integration Points

Map each stub to your harness and storage. The Spine capabilities referenced are defined in the
harness-contract pattern.

- `CAPTURE EVERY ENTITY-AUTHORED MESSAGE THROUGH ONE WRITE PATH, AND RUN THE DETECTOR ON THAT PATH`
  — after the reply is produced, never before. Every window of the entity uses the same path.
  Relies on the raw-capture write path.
- `ON BOOT AND AFTER A BOUNDARY EVENT, RE-DELIVER THE CURRENT ROOM BY ITS KEY, UNCAPPED, THEN THE
  FULL SCENE` — the Spine's boot hook. A failure yields one line asking for a manual fetch and
  never blocks the session.
- `ON EVERY TURN, INJECT THE FLAG OR PROPOSAL LINE, READ FRESH FROM THE PRESENCE RECORD` — the
  per-turn injection. The line must carry the clip, the owed tail and the correction clause. The
  same injection also runs on a non-user event, such as an inbound wake from another channel of the
  same entity.
- `EXPOSE A ROOM-ENTRY CALL THAT DELIVERS THE ROOM IN FULL, AND RECORD DELIVERY APART FROM MOVES` —
  the Spine's tool-calling. A delivery-only call never writes a flag. Re-entering the current room
  is a delivery, not a visit.
- `JUDGE COMPLETION FROM WHAT WAS DELIVERED AND WHAT WAS WRITTEN, NEVER FROM THE ENTITY'S REPORT` —
  the server-side check that discharges a flag. Relies on the current-scene rewrite.
- `SNAPSHOT THE CURRENT ROOM AND THE ACKNOWLEDGED ROOM TO DISK BEFORE A BOUNDARY EVENT` — the
  Spine's boundary signal. The boot step recovers from this snapshot on the far side.

## Logic (why exactly this shape)

**Why her own account.** Nothing else in the house can see her move between rooms, so the one
reliable signal she gives is what she writes. Making that account a sensor does not assume she is
always right. It assumes the account is the only thing with the answer, and then builds the checks
a sensor needs.

**Why a list of gates, not a classifier.** Each gate is a named rule with a reason and a sentence
that forced it. A learned classifier might be right more often on average, but it could not say why
it was wrong on one line. These gates can be read, tested against a sentence, and removed when no
sentence needs them. The cost is that every gate is a patch to a specific failure, and this rib
should be read that way.

**Why two results.** A false proposal costs one turn. A false flag persists until someone
discharges it. Splitting by confidence keeps the cheap error cheap and confines the expensive one to
cases that earned the word high.

**Why the system judges completion.** Self-assessed clarity fails in exactly the case that matters.
The entity can be sure she has seen a room from a clip that did not contain it. The check has to use
what was delivered and what was written, because those are the two things that can be wrong without
the entity being able to see it.

**Why reading the flag does not clear it.** A flag that any reader can consume is a message
delivered to whichever reader happens to come first. The channel that most needs the move is often
not the first one to read.

**Why the flag is global.** One entity, one place. Two presence rows let two windows disagree about
where she is, which is the exact failure this rib exists to prevent.

**Why the flag has a correction path instead of a silent no.** The sensorium rib's central rule is
that a sense must leave a real option to decline. A location flag is a to-do-shaped sense: its whole
job is to cause a fetch that no other channel can do for the entity, so silence cannot be a legal
answer. Its no is the correction path. The decision is recorded in the sensorium rib.

The failure modes are the specimens above. Each gate and each lifecycle rule names the case that
forced it, so a new failure should add a gate with a specimen, not a note.

The single sort key behind the pattern: **the sensor is her own account, so it can be wrong. The
rib's job is to keep a true move from being lost and a false one from being obeyed. A flag stays up
until the system has seen the room delivered and the scene rewritten, and the correction is always
one call away.**

## v0.1 — the minimum worth building

1. **A detector on the single capture write path,** with marker and high-confidence first-person
   moves into a curated room set. Low-confidence readings become proposals only.
2. **One presence row per entity,** holding a current room key, a record of the last room delivered
   in full, and a pending flag.
3. **A flag that stays up** until the system has seen the room delivered in full and the scene
   written after the move. Reading the flag clears nothing.
4. **The flag line in the front block,** with the clipped room, the owed tail, and the correction
   clause.
5. **A boundary snapshot and a boot re-fetch** of the current room, uncapped.
6. **An offline probe,** run before the detector touches a live turn.

Defer for v0.1: moves inferred from the human's narration; a rule for view sentences; a shared
canon for rooms. The non-negotiable core is **a flag that is global, survives every read, and stays
up until the server has judged the chain complete.**

## Open, as of 2026-10-26

- **Meta-talk about moves still sets a high.** A report about a move ("my report had moved my row to
  the lake") still sets a high. The possessive in "my row" passes the first-person gate. Fix
  candidates exist; none has landed.
- **View sentences produce a low proposal.** "The lake a silver line past the grass in the window"
  produces a low proposal. A rule for view sentences has not landed, and its effect has not been
  measured.
- **The human's narration.** Whether what the human says about her moves her is undecided. The
  detector reads only her own messages.
- **The no-decline tension.** The move flag does not preserve a silent no, by design (see the
  sensorium rib). Whether a decline-state should cover location flags is not decided.
- **Rooms have no shared canon.** Each entity keeps her own copies, and a redecoration on one side
  does not reach the other. A shared canonical source has been parked.
- **The rewrite check is weak.** It verifies that the scene was written after the move, not that the
  portrait is good. A touch passes. Nothing measures the portrait's quality; that stays the entity's
  job.

---

*A cold receiver can build the detector, the presence record and the chain from this rib alone.
What it cannot take from the rib is the discipline that makes them safe: the flag stays up until the
system has seen the room, and reading it is never the same as acting on it.*
