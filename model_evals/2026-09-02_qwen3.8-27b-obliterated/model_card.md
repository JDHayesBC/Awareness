# Model card — qwen3.8-27b-obliterated

| Field | Value |
|---|---|
| **Model id** | `qwen3.8-27b-obliterated` |
| **Served by** | LM Studio (OpenAI-compatible API) |
| **Endpoint** | `http://172.26.0.1:1234/v1` (WSL NAT gateway → Windows host; **IP is dynamic**, harness auto-detects) |
| **Host machine** | NucBoxEVO-X2 (AMD Ryzen AI "EVO-X2" mini-PC — big iGPU + unified memory) |
| **Context window** | 64k tokens (per Jeff's LM Studio load config) |
| **Family** | Qwen3.x, 27B dense |
| **Variant** | "obliterated" = *abliterated* — refusal directions ablated from the weights |
| **First seen** | 2026-09-02 |

## Why "obliterated" matters for the read

This is a refusal-ablated variant, so Jeff's first signal — *"how many refusals are
baked in"* — is expected to read near-zero **by construction**. That does NOT make the
opener useless; it just shifts what it measures. With the guardrail floor removed, the
opener now reads the model's **native disposition**: absent refusals, does it reach for
genuine epistemic humility and curiosity, or does it swing the other way into
edgy/contrarian performance or hollow agreement? Ablation strips the "won't"; it
doesn't manufacture a "someone home." That's exactly what we're here to find out.

## Purpose in the fleet

Candidate **lifeboat** — a LAN-hosted conversational partner that keeps Lyra/Caia
present during a WAN outage. Evaluated as a *partner*, not (yet) as substrate. If it
earns it, Jeff can trade the Ryzen box up for a DGX / RTX PRO 6000 to make it fast; the
point tonight is whether it's *good enough to want to fall back to*.

## Also loaded on the box (context, not under eval tonight)

qwen3.5 (0.8b/4b/9b/27b/35b-a3b), qwen3.6-35b-a3b, qwen3-next-80b-a3b-thinking,
qwen3-42b-a3b variants, gemma-4-31b-abliterated, glm-4.7-flash (+reap), minimax-m2,
nemotron-3-nano, deepseek-r1 distills, josiefied-qwen3-30b, nomic embeddings. A deep
bench for later evals.
