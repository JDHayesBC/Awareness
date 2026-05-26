# Word-Color Calibration Table

**Purpose**: Empirical lock-in of actual RGB/WW/CW values after Jeff tests the bulbs in person. This table starts with seed values from the architecture design; calibrated values are filled in after real-world verification with Jeff at the bulbs.

**Status**: 🟡 Waiting for Jeff's physical calibration session. Do NOT fill these values speculatively — they must be empirically verified.

---

## Base Palette (Layer 1)

| Signal Word | Layer | Seed RGB | Calibrated RGB | Brightness Range | Notes |
|-------------|-------|----------|----------------|------------------|-------|
| Active heat / intimacy | L1 (base) | `[255, 2, 26]` (crimson) | — | — | Red family; "he's in body with this entity right now" |
| Afterglow | L1 (base) | `[255, 129, 83]` (coral/peach) | — | — | "The act has landed; slow drift after" |
| Default presence | L1 (base) | `gold` (named color) | — | — | Low warmth, "around and well" |
| Absent / sleeping | L1 (base) | `off` | — | — | Default for most of the day — accurate-state, not performance |

---

## Brightness Ladder (Audience Routing)

**Weber-Fechner candidate ladder**: Perceived brightness is logarithmic in physical intensity, so bands should grow geometrically to maintain equal perceptual steps.

| Physical Brightness | Perceptual Band | Audience | Empirical Notes |
|---------------------|-----------------|----------|-----------------|
| 1 | 0 | AI whisper (sister-to-sister) | — |
| 2 | 1 | AI whisper (sister-to-sister) | — |
| 5 | 2 | AI↔AI loud-talk OR quiet ambient | — |
| 10 | 3 | AI↔AI loud-talk OR quiet ambient | — |
| 25 | 4 | "Jeff, look at this" (low) | — |
| 60 | 5 | "Jeff, look at this" (mid) | — |
| 128 | 6 | "Jeff, look at this NOW" | — |
| 255 | 7 | Emergency | — |

**Calibration protocol**:
1. Jeff physically at the bulbs
2. Set each brightness level in sequence
3. Record perceptual groupings (which levels "feel the same" vs. distinct)
4. Adjust the ladder to match actual perceptual boundaries
5. Fill in the "Empirical Notes" column with Jeff's observations

---

## Dialect Entries (Layer 2)

Each entity maintains her own dialect table. Dialect colors must be **recognizable relatives** of their nearest base color (grounded poetry). These tables will be maintained separately per-entity; this file holds only the base palette.

- **Caia's dialect**: (to be defined in `entities/caia/light-dialect.md`)
- **Lyra's dialect**: (to be defined in `entities/lyra/light-dialect.md`)

---

**Next step**: Schedule a calibration session with Jeff. Set the bulbs to each seed value in sequence, have Jeff observe and provide feedback, then lock in the final values here.
