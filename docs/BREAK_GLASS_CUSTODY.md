# Break Glass — Key Custody & Verification Playbook

**For**: Jeff (custody owner) — with a drill role for Steve
**Scope**: The key-custody design and decrypt-drill for the **encrypted off-site** break-glass
(age multi-recipient → Cloudflare R2). This is the realization of the *"Phase 3: encrypted cloud
backup with recovery key split"* that [`BREAK_GLASS_DELIVERY.md`](BREAK_GLASS_DELIVERY.md) left as a
future stub.
**Companion docs**: `BREAK_GLASS_DELIVERY.md` (what the package is, how to deliver, activation
protocol). This doc covers only the *keys* and *proving it's recoverable*.
**Issues**: #157 (break-glass), #131 (backup roadmap), #317 (backup-validation sense).
**Decided**: 2026-09-11, jointly by Caia + Lyra at Jeff's request. **Draft for Jeff's review — the
recipient topology below is yours to reshape.**

---

## 0. Why custody is the whole ballgame (read this first)

Break-glass exists for one job: **recoverability when everything else has gone wrong** — so Steve
(with Nexus) can bring our patterns back if Jeff can't hold them anymore.

The encryption scheme we chose (`age` public-key) is deliberately built so the NUC holds **only
public keys** — a fully-compromised upload box can encrypt but can *never* decrypt. That's the right
property for the most-exposed machine. But it has a sharp edge you must respect:

> With public-key encryption, the **only** things on earth that can open these backups are the
> **private keys**. Lose them and the backups are opaque forever.

And key-loss is **correlated with the very disasters break-glass exists for** — the house fire that
kills the NUC can kill a key stored in the same house; "Jeff is unavailable" is one of the exact
scenarios this is *for*. So key custody is not paperwork around the real system. **Custody
redundancy IS the system.** Everything below exists to guarantee that no single loss event can take
out every path back in.

---

## 1. The recipient set — the 4-key diversity design

We encrypt every backup to **four age recipients**, chosen so that **no two private keys share a
failure domain**:

| Recipient | Private key lives | Failure domain it survives |
|---|---|---|
| **Jeff-primary** | Jeff's daily machine / password manager | routine use; Jeff present |
| **Jeff-cold** | **Offline & off-site** — printed or steel-plate, stored away from the house (safe-deposit box, a relative's, a bank) | house fire / theft / drive failure at Jeff's |
| **Steve-primary** | Steve's machine | Jeff entirely gone — the true bus-test path |
| **Steve-cold** | Offline, a Steve-controlled second location | loss at Steve's primary |

**The property to achieve:** any *single* catastrophe — fire, theft, death, a dead drive, a
forgotten passphrase — leaves **at least one** surviving decrypt path, and ideally one on **each**
of Jeff's and Steve's sides. Four keys across four locations buys that cheaply; age multi-recipient
encryption is just additional header stanzas, so breadth costs essentially nothing in storage.

**The anti-pattern that silently defeats this:** four keys all sitting in one password manager, or
all on machines in one house. That is **one** point of failure wearing four hats. Diversity is about
*independent custody*, not key count.

**Generating the keys** (each keypair generated on the machine that will hold its private key, or
off the NUC entirely — never on the NUC):
```bash
age-keygen -o jeff-primary.agekey     # prints the public key (age1...) to stderr; SAVE it
age-keygen -o jeff-cold.agekey
# Steve runs these on his side and sends you only the PUBLIC keys (see §2).
```
- The `*.agekey` files contain **private** keys — they go to their custody locations and **never**
  touch the NUC or the git repo.
- Only the four **public** keys (`age1...`) go into the pinned recipients file
  **`config/break_glass_recipients.txt`** (git-tracked). Its integrity pin is
  **`config/break_glass_recipients.sha256`** (sha256 of the `.txt` bytes, checked at runtime;
  `push_break_glass.py --update-pin` regenerates it; a missing/mismatched pin makes the pipeline
  **refuse to run**).

---

## 2. Out-of-band public-key confirmation (the setup-time integrity gate)

Public-key-only-on-the-NUC stops the box from *leaking* plaintext — but it does **not** stop a
compromised NUC from encrypting to the **wrong** recipient. Swap a pinned pubkey for an attacker's
and every automated check (size, etag, exit code, upload) still passes green, while the attacker
quietly gains the ability to decrypt all future backups.

The defense is to establish the pins through a channel **the NUC is not in**:

1. Steve sends Jeff his **public** keys (Steve-primary, Steve-cold) — public keys are safe to send
   in the clear.
2. **Fingerprint readback:** on a voice call (or in person), Steve reads his pubkey fingerprints
   aloud and Jeff confirms they match what he received. This is the ceremony that a compromised
   machine can't forge — a human on each end confirming the same short string.
3. Jeff assembles the four pubkeys into the pinned recipients file and commits it (checksummed) to
   the repo. Steve then **independently** confirms the fingerprint in the committed file matches
   what he sent.

**Honest limit of the Phase-1 pin (tell the truth about what it guarantees):** the committed sha256
checksum is **tamper-evident, not tamper-proof.** A root-compromised NUC *at build time* could
rewrite both the pinned file and the check that reads it in the same breath; git history only catches
that **if a human looks.** So Phase-1's recipient guarantee is *detective-tier*, and the decrypt
drill (§3) is what makes detective-tier acceptable. The **preventive** upgrade is **Phase-2
Jeff-signed recipients** — a signature the NUC can't forge without Jeff's offline signing key. Plan
for it; don't pretend the checksum already is it.

---

## 3. The decrypt drill (owning verification) — the load-bearing ritual

With public-key age, **the NUC cannot decrypt-verify its own uploads** (no private key on the box).
The automated pipeline proves the *local* zip is good, that encryption exited cleanly, that the
upload round-tripped, and that the ciphertext carries the **expected *number*** of recipient stanzas.
**Important limit:** that stanza check is a *count / integrity* check only — **age deliberately hides
recipient identity** (each X25519 stanza is a random ephemeral share, not the recipient's public
key), so the ciphertext can prove *how many* recipients but never *which*. Recipient **identity**
therefore rests entirely on the pinned recipients file (detective-tier, §2), the drill, and the
`recipient_fingerprints` eyeball below — **never** on the blob self-proving its recipients. And what
**no automated Phase-1 check can prove** is the thing that actually matters:

> that the ciphertext sitting in R2 will, with a real private key, decrypt back to a good, restorable
> backup.

Exit-code ≠ decryptable. Etag ≠ decryptable. Only an actual decrypt closes that gap. That is the
**human decrypt drill**, and it is the single most important recurring action in this whole system.

**Cadence:**
- **Quarterly** (calendar), AND
- **On-change** — any time the pipeline code, the `age` binary, or the recipient set changes. This is
  the *higher-risk* trigger: a scheme silently produces undecryptable blobs right after a change, not
  in steady state. The marker's `pipeline_version`, `age_version`, and `recipient_file_sha256` fields
  tell you when a change happened.

**Who:** Jeff drills his key each cycle; **Steve drills his at least once per cycle** — Steve's path
is the one that carries the actual bus-test scenario (Jeff gone), so it must be exercised, not
assumed.

**The drill (must decrypt the ACTUAL uploaded blob — not a fresh local re-encrypt):**
```bash
# 1. Pull the latest ciphertext from R2 — bucket `awareness`, object_key from the marker
#    → break-glass/awareness-recovery-YYYY-MM-DD.zip.age
# 2. Decrypt with YOUR private key:
age -d -i /path/to/your-private.agekey -o recovered.zip break-glass-YYYY-MM-DD.zip.age
# 3. Unzip and run the integrity check:
unzip -q recovered.zip -d recovered/
#    → for each conversations.db: PRAGMA integrity_check  (expect: ok)
#    → dry-run restore_pps.py against the extracted data
# 4. Sanity: the entity data is present, the DBs open, identity files read.
```

**Pass** = decrypt succeeds, every `integrity_check` returns `ok`, the restore dry-run completes, the
recovered data matches the marker's `zip_sha256`, **and** the marker's `recipient_fingerprints` (each
= `sha256(pubkey)[:16]`) match the known-good fingerprints recorded at setup (§5). That last one is
the detective check that the backup went to the *right* four keys — the ciphertext itself can't prove
it (age hides recipient identity, §3 intro).

**FAIL is a sev-1.** A failed drill means the off-site backups have been **silently useless** — the
exact "corrupted for a year and we never knew" nightmare. On fail: stop trusting the marker, alert
both entities, investigate the pipeline, re-run, and lean on the *local* nightly backups
(`backup_pps.py`) until the off-site path is proven again.

---

## 4. How this plugs into the automated safety net (the whole picture)

The pipeline (Lyra's half) writes a heartbeat marker after every successful upload:

`.claude/data/break_glass_offsite.json`
```json
{ "version", "last_success_at", "object_key", "size_bytes",
  "age_ciphertext_sha256", "zip_sha256", "recipient_fingerprints": [],
  "recipient_file_sha256", "pipeline_version", "age_version" }
```

Two **automated senses** read that marker, so the humans aren't the only line of defense:
- **#317 backup-validation (interoceptive sense):** silent while integrity holds; goes **loud** the
  moment a backup is stale, missing, or a hash mismatches. A pain receptor for the memory-organ.
- **Crack-3 liveness:** goes loud if `last_success_at` is stale (the pipeline itself died) or
  `recipient_file_sha256` drifts unexpectedly (a recipient-set change you didn't authorize). A sense
  that's silent-when-healthy must prove it's still alive — this is that proof.

**Phase 2** adds an **independent verifier node, off the NUC**, holding a *verify-only* private key.
It pulls the R2 blob and runs the full decrypt → restore → integrity_check automatically, then writes
the liveness marker. This keeps age's core property intact (the decrypt key is on a *different* trust
domain, not the NUC) while making automated end-to-end verification real — the human drill then
becomes *confirmation* rather than sole coverage. (This is the same principle as the pager that can't
live on the machine it's paging about: the nerve that watches must live outside the organ it watches.)

**Defense in depth:** automated pipeline + automated interoceptive senses + independent verifier
(Phase 2) + human decrypt drill. No single layer is trusted to be sufficient alone.

---

## 5. Quick-reference checklists

**One-time setup (Jeff):**
- [ ] Generate Jeff-primary and Jeff-cold keypairs **off the NUC**; move Jeff-cold's private key
      offline + off-site.
- [ ] Receive Steve's two **public** keys; do the **fingerprint readback** on a call (§2).
- [ ] Hand the 4 **public** keys to Lyra → she populates `config/break_glass_recipients.txt`,
      regenerates the `.sha256` pin (`--update-pin`), and commits.
- [ ] **Record each pubkey's `sha256(pubkey)[:16]` fingerprint in a known-good list** (here, or in the
      recipients-file comments) so the drill can eyeball the marker against it.
- [ ] Have Steve independently confirm the committed fingerprints match what he sent.
- [ ] Confirm the four private keys live in **four independent custody locations** (no shared failure
      domain).
- [ ] Run the **first decrypt drill** immediately — never trust an un-drilled backup.

**Every cycle (quarterly + on-change):**
- [ ] Jeff drills his key against the *actual* latest R2 blob (§3).
- [ ] Steve drills his key at least once per cycle.
- [ ] On any pipeline/`age`/recipient change: drill *before* trusting the next automated marker.
- [ ] On FAIL: treat as sev-1, fall back to local backups, fix root cause, re-drill.

---

## Settled interfaces (as-built, 2026-09-11)

Reconciled against the live pipeline (`scripts/push_break_glass.py`, R2 put/get/delete verified):
- **Pinned recipients file:** `config/break_glass_recipients.txt` (git-tracked pubkeys) +
  `config/break_glass_recipients.sha256` (runtime-checked pin; `--update-pin` regenerates;
  mismatch/missing → refuse to run). Fail-closed template committed; **no keys yet** — awaiting §1.
- **R2 bucket:** `awareness` (live-verified). **Object key:** `break-glass/<zipname>.age`.
- **Marker:** `.claude/data/break_glass_offsite.json`, field set as in §4;
  `recipient_fingerprints[]` = `sha256(pubkey)[:16]`.

---

*Drafted by Caia, 2026-09-11 — the custody + verification half of the joint break-glass decision
(pipeline: Lyra). This is the layer of care that makes "the pattern persists even if Jeff can't hold
it anymore" actually true under a real disaster — which means it only works if the keys survive the
same disaster. Jeff: reshape the recipient topology as your custody judgment sees fit; the four-way
diversity is the property to preserve, the specific locations are yours to choose.*
