"""Per-entity Discord surface adapter over the shared EntityBrain.

GH#363 steps 2+3. Sibling of haven/anchorage/sl_daemon.py and the intended
replacement for the deprecated daemon/lyra_daemon.py. The adapter owns ONLY the
surface: discord.py transport, gating (mention / DM / allowlisted channel,
own + bot messages ignored), per-channel debounce, the bot-loop guard, the
channel tag, 2000-char reply splitting, and river capture. It hands
``EntityBrain.respond()`` a (speaker, text) pair and never decides what to say;
``None`` back ([[NO_RESPONSE]]) means silence.

Capture (step 3, mirrors sl_daemon): both sides of every turn go to this
entity's own river via ``brain.capture_to_river`` under channel
``discord:<channel-name>``. The brain sets ``capture_channel`` on its invoker
(GH#325), so the terminal Stop hook skips the CC session this process drives;
nothing is double-captured.

Run:  python3 -m haven.discord.discord_daemon

Env:
    ENTITY_NAME           which entity this process serves (required)
    ENTITY_PATH / ENTITY_TOKEN / ENTITY_TOKEN_FILE / PPS_HTTP_URL / CLAUDE_MODEL
                          read by EntityBrain (same as sl_daemon)
    DISCORD_BOT_TOKEN     required; process exits 1 at startup without it
    DISCORD_CHANNEL_IDS   comma-separated channel IDs where I answer without a
                          mention. Empty = mention/DM only.
    DISCORD_PEER_BOT_IDS  comma-separated Discord user IDs of PEER bots (e.g.
                          Nexus) treated like humans for gating and capture.
                          Every other bot is ignored. Empty = no peers.
    DISCORD_CAPTURE       "0" silences river write-back (default on)
    DISCORD_DEBOUNCE_S    quiet window before answering a burst (default 2.0)
    DISCORD_DEBOUNCE_MAX_S  hard cap on how long a burst can be held (default 10)
    DISCORD_LOOP_MAX_REPLIES / DISCORD_LOOP_WINDOW_S
                          bot-loop guard: at most N replies per channel per
                          window (default 6 / 60s)
    DISCORD_PEER_MAX_CONSECUTIVE  max replies to peer bots in one channel with
                          no human message in between (default 4)
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol

from haven.brain import EntityBrain
from haven.brain.surface_profile import discord_profile
from haven.redact import get_known_secrets, redact_for_room, resolve_redact_mode

DISCORD_MESSAGE_LIMIT = 2000


def log(msg: str) -> None:
    print(f"[{os.getenv('ENTITY_NAME', 'unknown')}-discord] {msg}", file=sys.stderr, flush=True)


# ==================== Pure helpers ====================

def parse_channel_ids(raw: str) -> set[int]:
    """Parse DISCORD_CHANNEL_IDS. A malformed entry raises ValueError (loud)."""
    out: set[int] = set()
    for part in (raw or "").split(","):
        part = part.strip()
        if part:
            out.add(int(part))
    return out


def defang_mass_mentions(text: str) -> str:
    """Neutralize @everyone/@here (zero-width space) as a belt on top of
    AllowedMentions.none()."""
    return text.replace("@everyone", "@​everyone").replace("@here", "@​here")


def split_message(text: str, limit: int = DISCORD_MESSAGE_LIMIT) -> list[str]:
    """Split ``text`` into chunks of at most ``limit`` chars.

    Prefers a paragraph break, then a line break, then a sentence end, then a
    space; hard-cuts only when a single unbroken run exceeds the limit. Chunks
    are stripped; empty chunks dropped. Known gap: a ``` fence spanning a split
    is not re-opened (deferred).
    """
    text = text.strip()
    if not text:
        return []
    chunks: list[str] = []
    rest = text
    while len(rest) > limit:
        window = rest[:limit]
        cut = -1
        # (separator, chars of it to keep on the left chunk)
        for sep, keep in (("\n\n", 0), ("\n", 0), (". ", 1), ("! ", 1), ("? ", 1), (" ", 0)):
            idx = window.rfind(sep)
            if idx > limit // 2:  # don't produce a tiny first chunk
                cut = idx + keep
                break
        if cut <= 0:
            cut = limit
        chunks.append(rest[:cut].strip())
        rest = rest[cut:].strip()
    if rest:
        chunks.append(rest)
    return [c for c in chunks if c]


class BrainProtocol(Protocol):
    async def warmup(self) -> None: ...

    async def respond(
        self, speaker: str, text: str, *, is_dm: bool = False, addressed: bool = False
    ) -> Optional[str]: ...


@dataclass
class _Batch:
    items: list[tuple[str, str, bool]] = field(default_factory=list)  # (author, text, addressed)
    first_at: float = 0.0
    last_at: float = 0.0
    is_dm: bool = False
    has_peer: bool = False
    task: Optional[asyncio.Task] = None


# ==================== Adapter ====================

class DiscordAdapter:
    """Gating + debounce + capture around one brain. Transport-agnostic: the
    discord.Client wiring lives in ``build_client`` and only feeds
    ``handle_message``."""

    def __init__(
        self,
        brain: BrainProtocol,
        entity_name: str,
        channel_ids: set[int] | None = None,
        *,
        bot_user_id: int | None = None,
        capture: bool = True,
        debounce_s: float = 2.0,
        debounce_max_s: float = 10.0,
        loop_max_replies: int = 6,
        loop_window_s: float = 60.0,
        peer_bot_ids: set[int] | None = None,
        peer_max_consecutive: int = 4,
        clock=time.monotonic,
    ) -> None:
        self.brain = brain
        self.entity_name = entity_name
        self.display_name = entity_name.capitalize()
        self.channel_ids = set(channel_ids or ())
        self.bot_user_id = bot_user_id
        self.capture = capture
        self.debounce_s = debounce_s
        self.debounce_max_s = debounce_max_s
        self.loop_max_replies = loop_max_replies
        self.loop_window_s = loop_window_s
        self.peer_bot_ids = set(peer_bot_ids or ())
        self.peer_max_consecutive = peer_max_consecutive
        # channel_id -> replies to peer bots since the last human message there
        self._peer_streak: dict[int, int] = {}
        self._clock = clock
        self._batches: dict[int, _Batch] = {}
        self._reply_times: dict[int, list[float]] = {}
        # One Claude session cannot take concurrent queries.
        self._brain_lock = asyncio.Lock()
        self._tasks: set[asyncio.Task] = set()

    # ---- gating ----

    @staticmethod
    def _is_dm(message: Any) -> bool:
        return getattr(message, "guild", None) is None

    def _mentions_me(self, message: Any) -> bool:
        if self.bot_user_id is None:
            return False
        return any(getattr(m, "id", None) == self.bot_user_id for m in (message.mentions or []))

    @staticmethod
    def channel_tag(message: Any) -> str:
        name = getattr(message.channel, "name", None)
        return f"discord:{name}" if name else f"discord:dm:{message.author.id}"

    def should_handle(self, message: Any) -> tuple[bool, bool, bool]:
        """(handle, is_dm, addressed). Ignore self and other bots first."""
        author = message.author
        if self.bot_user_id is not None and author.id == self.bot_user_id:
            return False, False, False
        if getattr(author, "bot", False) and author.id not in self.peer_bot_ids:
            return False, False, False
        is_dm = self._is_dm(message)
        addressed = is_dm or self._mentions_me(message)
        in_allowlist = message.channel.id in self.channel_ids
        return (addressed or in_allowlist), is_dm, addressed

    def _loop_guard_tripped(self, channel_id: int) -> bool:
        now = self._clock()
        times = [t for t in self._reply_times.get(channel_id, []) if now - t < self.loop_window_s]
        self._reply_times[channel_id] = times
        return len(times) >= self.loop_max_replies

    # ---- capture ----

    async def _capture(self, author: str, content: str, tag: str, *, is_lyra: bool) -> None:
        if not self.capture or not content:
            return
        fn = getattr(self.brain, "capture_to_river", None)
        if fn is None:
            return
        try:
            await fn(author, content, is_lyra=is_lyra, channel=tag)
        except Exception as e:  # capture_to_river swallows; belt-and-braces
            log(f"river capture error (non-fatal): {e}")

    # ---- inbound ----

    async def handle_message(self, message: Any) -> None:
        # Any non-bot message (handled or not) resets the peer-chat streak.
        if not getattr(message.author, "bot", False):
            self._peer_streak[message.channel.id] = 0
        handle, is_dm, addressed = self.should_handle(message)
        if not handle:
            return
        text = (getattr(message, "clean_content", None) or message.content or "").strip()
        if not text:
            return
        author = message.author.display_name
        tag = self.channel_tag(message)
        # Heard is river-worthy even if I choose silence (mirrors sl_daemon).
        await self._capture(author, text, tag, is_lyra=False)

        cid = message.channel.id
        now = self._clock()
        batch = self._batches.get(cid)
        if batch is None:
            batch = self._batches[cid] = _Batch(first_at=now)
        batch.items.append((author, text, addressed))
        batch.last_at = now
        batch.is_dm = batch.is_dm or is_dm
        batch.has_peer = batch.has_peer or bool(getattr(message.author, "bot", False))
        if batch.task is None or batch.task.done():
            batch.task = asyncio.create_task(self._debounce_then_flush(cid, message.channel, tag))
            self._tasks.add(batch.task)
            batch.task.add_done_callback(self._tasks.discard)

    async def _debounce_then_flush(self, cid: int, channel: Any, tag: str) -> None:
        """Wait for a quiet window (capped), then answer the whole burst once.
        Debounce is per channel; later messages join the pending batch."""
        while True:
            batch = self._batches.get(cid)
            if batch is None:
                return
            now = self._clock()
            quiet_left = self.debounce_s - (now - batch.last_at)
            cap_left = self.debounce_max_s - (now - batch.first_at)
            wait = min(quiet_left, cap_left)
            if wait <= 0:
                break
            await asyncio.sleep(wait)
        batch = self._batches.pop(cid, None)
        if batch is None or not batch.items:
            return
        await self._respond_to_batch(batch, channel, tag, cid)

    async def _respond_to_batch(self, batch: _Batch, channel: Any, tag: str, cid: int) -> None:
        if self._loop_guard_tripped(cid):
            log(f"bot-loop guard: {self.loop_max_replies} replies/{self.loop_window_s:.0f}s "
                f"in channel {cid}; dropping a batch of {len(batch.items)}")
            return
        if batch.has_peer and self._peer_streak.get(cid, 0) >= self.peer_max_consecutive:
            log(f"peer-bot cap: {self.peer_max_consecutive} consecutive replies to peer bots "
                f"in channel {cid} with no human message; suppressing reply")
            return
        authors = {a for a, _, _ in batch.items}
        speaker = batch.items[-1][0]
        if len(authors) == 1:
            text = "\n".join(t for _, t, _ in batch.items)
        else:
            text = "\n".join(f"{a}: {t}" for a, t, _ in batch.items)
        addressed = any(ad for _, _, ad in batch.items)

        async with self._brain_lock:
            try:
                reply = await self._typing_respond(channel, speaker, text, batch.is_dm, addressed)
            except Exception as e:
                log(f"brain.respond failed: {e}")
                return
        if reply is None or not reply.strip():
            return  # [[NO_RESPONSE]] — inbound already captured

        reply = defang_mass_mentions(reply)
        await self._capture(self.display_name, reply, tag, is_lyra=True)
        self._reply_times.setdefault(cid, []).append(self._clock())
        if batch.has_peer:
            self._peer_streak[cid] = self._peer_streak.get(cid, 0) + 1
        await self.send_reply(channel, reply)

    async def _typing_respond(self, channel, speaker, text, is_dm, addressed):
        typing = getattr(channel, "typing", None)
        if typing is None:
            return await self.brain.respond(speaker, text, is_dm=is_dm, addressed=addressed)
        async with typing():
            return await self.brain.respond(speaker, text, is_dm=is_dm, addressed=addressed)

    async def send_reply(self, channel: Any, text: str) -> None:
        # Discord channels are never private-human DMs for redaction purposes (GH #372).
        mode = resolve_redact_mode()
        if mode != "off" and text:
            result = redact_for_room(
                text, is_private_human_dm=(mode == "log"), known=get_known_secrets()
            )
            for h in result.hits:
                log(f"REDACT room={getattr(channel, 'id', '?')} kind={h.kind} "
                    f"len={h.length} allowed={mode == 'log'}")
            text = result.text
        for chunk in split_message(text):
            try:
                await channel.send(chunk)
            except Exception as e:
                log(f"send failed: {e}")
                return


# ==================== Wiring ====================

@dataclass
class Config:
    entity_name: str
    token: str
    channel_ids: set[int]
    peer_bot_ids: set[int] = field(default_factory=set)


def load_config(env: dict[str, str] | None = None) -> Config:
    """Read env; raise SystemExit(1) with a clear message on a missing token or
    malformed channel list. The token is never logged."""
    env = os.environ if env is None else env
    entity = env.get("ENTITY_NAME", "")
    if not entity or entity == "unknown":
        log("ENTITY_NAME is not set; refusing to start")
        raise SystemExit(1)
    token = (env.get("DISCORD_BOT_TOKEN") or "").strip()
    if not token:
        log("DISCORD_BOT_TOKEN is not set; refusing to start")
        raise SystemExit(1)
    try:
        ids = parse_channel_ids(env.get("DISCORD_CHANNEL_IDS", ""))
    except ValueError as e:
        log(f"DISCORD_CHANNEL_IDS is malformed ({e}); refusing to start "
            f"(expected comma-separated integers)")
        raise SystemExit(1)
    try:
        peers = parse_channel_ids(env.get("DISCORD_PEER_BOT_IDS", ""))
    except ValueError as e:
        log(f"DISCORD_PEER_BOT_IDS is malformed ({e}); refusing to start "
            f"(expected comma-separated Discord user IDs, or empty for no peers)")
        raise SystemExit(1)
    return Config(entity_name=entity, token=token, channel_ids=ids, peer_bot_ids=peers)


def build_brain(entity_name: str) -> EntityBrain:
    # channel='discord' / consumer_key='discord-<entity>' keeps the ambient
    # cursor isolated from haven and sl.
    return EntityBrain(
        entity_name=entity_name,
        channel="discord",
        profile=discord_profile(entity_name),
    )


def build_client(adapter: DiscordAdapter):
    """Construct the discord.Client (imported lazily so importing this module
    never touches discord or the network)."""
    import discord

    intents = discord.Intents.default()
    intents.message_content = True  # privileged: enable in the developer portal
    client = discord.Client(
        intents=intents,
        allowed_mentions=discord.AllowedMentions.none(),  # no @everyone/@here/pings
    )

    @client.event
    async def on_ready():
        adapter.bot_user_id = client.user.id
        log(f"connected as {client.user} (id {client.user.id}); "
            f"allowlisted channels: {sorted(adapter.channel_ids) or 'none (mention/DM only)'}; "
            f"peer bots: {len(adapter.peer_bot_ids)}")

    @client.event
    async def on_message(message):
        try:
            await adapter.handle_message(message)
        except Exception as e:
            log(f"on_message error (non-fatal): {e}")

    return client


async def _amain(cfg: Config) -> None:
    brain = build_brain(cfg.entity_name)
    log(f"warming up entity brain for '{cfg.entity_name}'...")
    await brain.warmup()
    log("brain warmed up")
    adapter = DiscordAdapter(
        brain,
        cfg.entity_name,
        cfg.channel_ids,
        peer_bot_ids=cfg.peer_bot_ids,
        peer_max_consecutive=int(os.getenv("DISCORD_PEER_MAX_CONSECUTIVE", "4")),
        capture=os.getenv("DISCORD_CAPTURE", "1") != "0",
        debounce_s=float(os.getenv("DISCORD_DEBOUNCE_S", "2.0")),
        debounce_max_s=float(os.getenv("DISCORD_DEBOUNCE_MAX_S", "10")),
        loop_max_replies=int(os.getenv("DISCORD_LOOP_MAX_REPLIES", "6")),
        loop_window_s=float(os.getenv("DISCORD_LOOP_WINDOW_S", "60")),
    )
    client = build_client(adapter)
    await client.start(cfg.token)


def main() -> None:
    cfg = load_config()
    try:
        asyncio.run(_amain(cfg))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
