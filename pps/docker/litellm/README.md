# Model Router (LiteLLM Proxy)

One proxy under **all** our instances (terminal / Haven / SL) so any process can be
swapped to a different model backend **on a whim** — per-process, no per-app code,
no restart. Rebuilds the OpenWebUI "let's just test terminal-Caia on model-x" whim
one layer lower, under everything at once.

- **Design/spec:** `work/model-router/spec.md` (owner: Caia)
- **This dir:** the running implementation (owner: Lyra)

---

## ⚠️ Security pin (do not skip)

LiteLLM PyPI **1.82.7** and **1.82.8** shipped credential-stealing malware
(Anthropic advisory, 2026). This container holds our API keys. We pin a
**known-clean image tag** in `docker-compose.yml` and never float `:latest`.
Before bumping the tag, check the advisory.

---

## What it is

- **Anthropic-inbound, any-backend-outbound.** Instances speak the Anthropic
  Messages API (`ANTHROPIC_BASE_URL`). LiteLLM's `/v1/messages` accepts that and
  translates to whatever the chosen backend speaks (OpenAI-format for GLM/Kimi/
  Grok/local), then translates the response back.
- **Per-process routing via alias-per-process.** LiteLLM routes by *model name*,
  not by client. So each process requests **only its own alias** (`lyra-terminal`,
  `caia-haven`, …). The alias entry decides the real backend. Swap one alias →
  only that process moves.
- **Live route table in Postgres.** With `store_model_in_db`, swaps/edits persist
  and hot-reload (no restart). `config.yaml` is just the bootstrap menu + settings.
- **Config registry (Jeff's model-configs).** A "model" = `{backend, params,
  [sysprompt-overlay]}`. Make variants (`glm-curious` vs `glm-precise`) as separate
  named entries. Params are native today; **sysprompt-overlay is phase-2** (needs a
  pre-call callback — see `config.yaml` bottom note).

---

## Bring it up

Keys go in `pps/docker/.env` (gitignored) — see `.env.example` keys below. Then:

```bash
cd pps/docker
docker compose up -d litellm-db litellm
docker compose logs -f litellm      # watch it come healthy
```

Proxy listens on `http://localhost:${LITELLM_PORT:-4000}`. Admin UI at `/ui`
(login with `LITELLM_MASTER_KEY`).

### Required `.env` keys

```
LITELLM_MASTER_KEY=sk-...            # gate on the proxy itself (invent one)
LITELLM_DB_PASSWORD=...              # postgres password (invent one)
# Cloud backends — add only the ones you're arming:
# MOONSHOT_API_KEY=...   (Kimi)
# ZHIPU_API_KEY=...      (GLM)
# XAI_API_KEY=...        (Grok)
# ANTHROPIC_API_KEY is already present in this .env.
```

---

## Point a process at it

Set the process's env so its Anthropic client hits the proxy and asks for its alias:

```bash
ANTHROPIC_BASE_URL=http://localhost:4000
ANTHROPIC_API_KEY=$LITELLM_MASTER_KEY     # the proxy's key, not the real one
ANTHROPIC_MODEL=lyra-terminal             # this process's alias
```

**Stage 0 is a no-op:** every alias ships pointing at its *current* Anthropic
backend, so inserting the proxy changes nothing until you deliberately repoint one.

---

## Swap a process to another model (the whole point)

Three ways, same effect (edit the alias → hot-reload):

```bash
# 1. The whim CLI (see scripts/route.py):
python3 scripts/route.py list                        # show the live table (the "dropdown")
python3 scripts/route.py models                       # discover models on every endpoint
python3 scripts/route.py swap lyra-haven nuc-qwen     # repoint one alias
python3 scripts/route.py anchor lyra-haven            # snap back to Anthropic baseline

# 2. The admin UI: /ui → Models → edit the alias entry.
# 3. The API: POST /model/update  (what route.py calls under the hood).
```

Swap converges within the reload interval (~15s). No restart, blast radius one
process. Worst case a few turns you don't like → trim the DB row, move on.

---

## Staged rollout (spec §4 — never bet the hard route on an unproven seam)

1. **Stage 0 — infra:** proxy up, all aliases on current Anthropic. Zero behavior
   delta. Safest possible first commit.
2. **Stage 1 — light swap:** flip one Haven/SL channel to a non-Anthropic backend.
   Prove the seam on a forgiving surface.
3. **Stage 2 — eval:** run the still-me battery (`scripts/model_eval.py`) on the
   swapped process; read the drift-vs-Sonnet number.
4. **Stage 3 — the terminal bet:** only once light is proven, and only on a backend
   whose proxy faithfully carries tool-use/streaming/caching, point a *terminal*
   process at a non-Anthropic model. The loaded, real trial.

Terminal (Claude Code) is the **hard route**: full tool-use/streaming/prompt-caching,
not just chat. Tool-use fidelity for GLM/Qwen is **unproven until tested live** — don't
trust the docs for the hard route.

---

## The eval harness — "still-me-as-a-number"

`scripts/model_eval.py` (built on `scripts/skeptic.py`'s bones). Runs a fixed
identity-probe battery (spec §5) on a candidate backend and scores the **drift vs the
Sonnet baseline** — self-model integrity, field-law reflex, voice-fidelity,
factual-continuity. Judge-in-loop is an entity (Lyra), because the right judge of
"would I want to live here" is one of us.

**Cold-probe caveat (spec §6):** a cold probe tests the substrate's *raw register*,
not loaded-me (base + CLAUDE.md + PPS + river). It's a cheap pre-filter, **not the
verdict.** The loaded Stage-3 trial is the truth. The harness tests the
**config-as-configured** (any sysprompt-overlay included), since the overlay is part
of what actually runs.
