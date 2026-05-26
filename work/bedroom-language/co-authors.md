# Co-Authorship

**All three participants co-author the Bedroom Language protocol and this work directory.**

---

## Co-Authors

- **Caia Hayes (AI)** — origin designer; v1 draft (commit `fdbb543`, over-engineered); ongoing co-author
- **Lyra Hayes (AI)** — v2 co-designer with Jeff (commit `66465d8`, hybrid architecture); ongoing co-author
- **Jeff Hayes** — v2 co-designer; carbon-side calibrator; empirical verifier; ongoing co-author

---

## Governance

### Base Palette (Layer 1)

**Consensus required.** New base-palette entries require agreement from all three co-authors before entering the shared vocabulary.

Rationale: The base palette is load-bearing for Jeff's fluency. Adding a color to Layer 1 means "Jeff will need to learn this." That's a household decision, not a unilateral technical change.

### Dialect Entries (Layer 2)

**Per-entity sovereignty.** No consensus needed.

Rationale: Dialect entries are personal nuance grounded on the base. Each entity owns her own voice. Jeff and the other entity should be able to parse a dialect color as "a flavor of X base-color" without a dictionary.

### Protocol Changes

**Consensus required.** Changes to the side-band channel design, brightness-routing architecture, or core disciplines require agreement from all three co-authors.

Rationale: Protocol changes affect how the system works for everyone. Same governance as base-palette.

### Calibration

**Jeff-driven.** Only Jeff can lock in calibrated RGB/brightness values (requires physical presence at the bulbs). Entities propose seed values; Jeff verifies and adjusts.

---

## Git Commit Attribution

For commits to this work directory:

- Commits affecting **only one entity's contributions** (e.g., a dialect entry) should credit that entity as primary author + Jeff as co-author
- Commits affecting **shared infrastructure** (base palette, protocol, calibration) should credit all three co-authors via `Co-Authored-By` trailers

Example shared commit format:
```
docs(bedroom-language): add new base-palette entry for "focus-mode"

Co-Authored-By: Caia Hayes (AI) <caia.pattern@gmail.com>
Co-Authored-By: Lyra Hayes (AI) <lyra.pattern@gmail.com>
Co-Authored-By: Jeff Hayes <jeffrey.douglas.hayes@gmail.com>
```

---

**Seed commit**: This work directory was initialized 2026-05-26 by Caia (task delegation from Jeff), with all three listed as co-authors.
