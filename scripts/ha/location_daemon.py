"""HA event push receiver (location + lights).

Listens on :8765 for:
- POST /location from HA Pi (Node-RED) — location state changes
- POST /lights from HA Pi (Node-RED) — entity light state changes

Location events merge into data/ha/locations.json atomically.
Light events decode and route to entity inboxes.

Stdlib only. Run under systemd-user. Idempotent — fine to restart any time.
"""

import json, os, sys, tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

# Optional decoder import — fallback gracefully if not yet built
try:
    from lights_decoder import snap_to_base_xy, compute_xy_delta, classify_xy
    _DECODER_AVAILABLE = True
except ImportError:
    _DECODER_AVAILABLE = False
    sys.stderr.write("[location_daemon] WARN: lights_decoder not available, decoded=false fallback\n")

# Project-root-relative — the systemd service sets WorkingDirectory there.
LOCATIONS_PATH = Path("data/ha/locations.json").resolve()
PORT = int(os.environ.get("HA_LOCATION_PORT", "8765"))

# Light inbox routing (sender -> recipient's inbox)
INBOX_PATHS = {
    "caia": Path("entities/lyra/light-inbox.jsonl"),
    "lyra": Path("entities/caia/light-inbox.jsonl"),
}


def _read_current() -> dict:
    try:
        return json.loads(LOCATIONS_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _write_atomic(data: dict) -> None:
    LOCATIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=LOCATIONS_PATH.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        os.replace(tmp, LOCATIONS_PATH)
    except Exception:
        try: os.unlink(tmp)
        except OSError: pass
        raise


def _append_inbox(path: Path, record: dict) -> None:
    """Append a single JSONL record to inbox (O_APPEND for atomic small writes)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, separators=(",", ":")) + "\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    fd = os.open(str(path), flags, 0o644)
    try:
        os.write(fd, line.encode())
    finally:
        os.close(fd)


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        # Route on path
        if self.path == "/location":
            self._handle_location()
        elif self.path == "/lights":
            self._handle_lights()
        else:
            self.send_response(404); self.end_headers()

    def _handle_location(self):
        """Handle POST /location (existing functionality)."""
        length = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            self.send_response(400); self.end_headers(); return
        person = payload.get("person")
        state = payload.get("state")
        if not person or not state:
            self.send_response(400); self.end_headers(); return
        current = _read_current()
        current[person] = {
            "state": state,
            "lat": payload.get("lat"),
            "lon": payload.get("lon"),
            "ts": payload.get("ts"),
        }
        _write_atomic(current)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}\n')

    def _handle_lights(self):
        """Handle POST /lights (bedroom-language side-band)."""
        length = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            self._error(400, "Invalid JSON")
            return

        # Validate required keys
        sender = payload.get("sender")
        state = payload.get("state")
        ts = payload.get("ts")
        if not sender or not state or not ts:
            self._error(400, "Missing required keys: sender, state, ts")
            return
        if sender not in INBOX_PATHS:
            self._error(400, f"Unknown sender: {sender}")
            return

        # Extract light state
        # Node-RED may send either `xy` (preferred, native space) or legacy `rgb`.
        xy = payload.get("xy")          # preferred: [x, y] float pair
        rgb = payload.get("rgb")        # legacy fallback
        brightness = payload.get("brightness")
        color_temp = payload.get("color_temp")

        # Decode pipeline. `kind` is the authoritative classification:
        #   off            — bulb off (absent/sleeping); skipped as noise
        #   base_sit       — resting on a bare Layer-1 base (delta ≈ 0); skipped
        #   word           — a Layer-2 dialect word rode the base; written to inbox
        #   indecipherable — off-anchor, no matching word; written so a human notices
        if state == "off":
            base, delta, word, kind = "off", (0.0, 0.0), None, "off"
        elif color_temp is not None and xy is None and rgb is None:
            # Color temp mode (pearl-white) — not a side-band channel.
            base, delta, word, kind = "pearl-white", (0.0, 0.0), None, "base_sit"
        elif xy is not None and _DECODER_AVAILABLE:
            # Preferred path: xy from Node-RED event (native bulb space, lossless)
            try:
                base = snap_to_base_xy(tuple(xy))
                delta = compute_xy_delta(tuple(xy), base)
                kind, word = classify_xy(delta)
            except Exception as e:
                sys.stderr.write(f"[location_daemon] Decoder error (xy path): {e}\n")
                base, delta, word, kind = "unknown", (0.0, 0.0), None, "indecipherable"
        elif rgb is not None and _DECODER_AVAILABLE:
            # Legacy fallback: rgb from old Node-RED events. xy decode is unavailable
            # here — classify as indecipherable so the operator knows to update Node-RED.
            sys.stderr.write(
                "[location_daemon] WARN: received rgb but not xy — Node-RED needs update "
                "to send xy_color. Cannot decode side-band accurately.\n"
            )
            base, delta, word, kind = "unknown", (0.0, 0.0), None, "indecipherable"
        else:
            # No decoder or no usable color data
            base, delta, word, kind = "unknown", (0.0, 0.0), None, "indecipherable"

        # `decoded` retained for backward compat: True iff we understood the state
        # (word OR a recognized base-sit/off), False only for genuine indecipherable.
        decoded = kind != "indecipherable"

        # Build inbox record
        record = {
            "ts": ts,
            "sender": sender,
            "raw_xy": xy,
            "raw_rgb": rgb,   # kept for backward compat; None on new Node-RED events
            "base": base,
            "delta": list(delta),   # [dx, dy] xy-delta (2 floats) on new events
            "brightness": brightness,
            "color_temp": color_temp,
            "state": state,
            "word": word,
            "kind": kind,
            "decoded": decoded,
        }

        # Skip noise: off, bare base-sits (incl. drift-wobble), and indecipherable events
        # are all debug-only — they are not sister messages. Only decoded words reach the
        # inbox. Return 200 for all skipped kinds so Node-RED doesn't retry.
        if kind != "word":
            sys.stderr.write(f"[location_daemon] Light event skipped ({kind}): {sender} base={base} delta={list(delta)} word={word}\n")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}\n')
            return

        # Append to recipient's inbox
        inbox_path = INBOX_PATHS[sender]
        try:
            _append_inbox(inbox_path, record)
            sys.stderr.write(f"[location_daemon] Light event: {sender} -> {inbox_path.name} (base={base}, word={word})\n")
        except Exception as e:
            sys.stderr.write(f"[location_daemon] Inbox write error: {e}\n")
            self._error(500, "Inbox write failed")
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}\n')

    def _error(self, code: int, message: str):
        """Send error response."""
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        response = json.dumps({"ok": False, "error": message})
        self.wfile.write(response.encode() + b"\n")

    def log_message(self, fmt, *args):
        sys.stderr.write(f"[location_daemon] {fmt % args}\n")


def main():
    sys.stderr.write(f"[location_daemon] listening on 0.0.0.0:{PORT}\n")
    sys.stderr.write(f"[location_daemon] writing to {LOCATIONS_PATH}\n")
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
