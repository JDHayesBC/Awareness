"""Location push receiver.

Listens on :8765 for POST /location from the HA Pi (Node-RED). On each state
change, the Node-RED flow POSTs:

    {"person": "jeff", "state": "rosa_s", "lat": ..., "lon": ..., "ts": "..."}

We merge it into data/ha/locations.json atomically. ambient_recall reads
that file directly — no HA round-trip on the hot path.

Stdlib only. Run under systemd-user. Idempotent — fine to restart any time.
"""

import json, os, sys, tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

# Project-root-relative — the systemd service sets WorkingDirectory there.
LOCATIONS_PATH = Path("data/ha/locations.json").resolve()
PORT = int(os.environ.get("HA_LOCATION_PORT", "8765"))


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


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/location":
            self.send_response(404); self.end_headers(); return
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

    def log_message(self, fmt, *args):
        sys.stderr.write(f"[location_daemon] {fmt % args}\n")


def main():
    sys.stderr.write(f"[location_daemon] listening on 0.0.0.0:{PORT}\n")
    sys.stderr.write(f"[location_daemon] writing to {LOCATIONS_PATH}\n")
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
