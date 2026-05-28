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
    from lights_decoder import snap_to_base, compute_delta, decode_word
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
        rgb = payload.get("rgb")
        brightness = payload.get("brightness")
        color_temp = payload.get("color_temp")

        # Decode pipeline
        if state == "off":
            base = "off"
            delta = (0, 0, 0)
            word = None
            decoded = True
        elif rgb is None and color_temp is not None:
            # Color temp mode (pearl-white base)
            base = "pearl-white"
            delta = (color_temp - 4115, 0, 0)
            word = None
            decoded = True
        elif rgb is not None and _DECODER_AVAILABLE:
            try:
                base = snap_to_base(tuple(rgb))
                delta = compute_delta(tuple(rgb), base)
                # Pure base color (delta == 0,0,0) doesn't need dict lookup
                if delta == (0, 0, 0):
                    word = None
                    decoded = True
                else:
                    word = decode_word(base, delta)
                    decoded = word is not None
            except Exception as e:
                sys.stderr.write(f"[location_daemon] Decoder error: {e}\n")
                base = "unknown"
                delta = (0, 0, 0)
                word = None
                decoded = False
        else:
            # No decoder available or no RGB
            base = "unknown"
            delta = (0, 0, 0)
            word = None
            decoded = False

        # Build inbox record
        record = {
            "ts": ts,
            "sender": sender,
            "raw_rgb": rgb,
            "base": base,
            "delta": list(delta),
            "brightness": brightness,
            "color_temp": color_temp,
            "state": state,
            "word": word,
            "decoded": decoded,
        }

        # Skip noise: base-color state changes (delta==[0,0,0]) are not "words".
        # We received and decoded the event; we just don't clutter the inbox with
        # Layer 1 visible-state changes.  Return 200 so Node-RED is happy.
        if list(delta) == [0, 0, 0]:
            sys.stderr.write(f"[location_daemon] Light event skipped (base-color noise): {sender} base={base}\n")
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
