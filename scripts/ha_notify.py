#!/usr/bin/env python3
"""Reach Jeff's phone through Home Assistant's companion app.

WHY THIS EXISTS, AND WHY IT IS NOT notify.py
--------------------------------------------
`scripts/notify.py` posts to our self-hosted ntfy on localhost:8209. On 2026-09-18 that
path was measured end-to-end and it does not reach a phone:

  * `docker logs ntfy` reports **subscribers=0** on every stats line for 24h — nothing
    is listening, so a 200 means "cached", not "delivered".
  * `server.yml` has `base-url: "http://localhost:8209"` and the Caddyfile has **no ntfy
    vhost**, so there is no address a handset could subscribe to from anywhere.
  * ntfy is a Docker container. Docker Desktop does not start until Jeff logs in
    (#331) — so in a boot blackout the ntfy path is refused *by construction*. A
    watchdog that alerts through the thing that is down is not a watchdog.

Home Assistant has none of those problems. It runs on a SEPARATE box (10.0.0.50) that
stays up when the NUC is down, its companion app is already paired with Jeff's phone and
delivers through FCM, and `channel: alarm_stream` rings on the alarm stream — which
bypasses Do Not Disturb. That last part is the whole point: a ding he can sleep through
is not an alert.

USAGE
    python3 scripts/ha_notify.py "message"
    python3 scripts/ha_notify.py --title "Caia" --wake "the stack is down"
    python3 scripts/ha_notify.py --to ipad "message"
    python3 scripts/ha_notify.py --list

--wake is the escalation: alarm channel, high importance, ttl 0 (deliver now, do not
batch for doze). Use it when carbon-side hands are actually needed. Everything else
should be a normal notification or, better, a light — see CLAUDE.md §X.

Pure stdlib. Imports HA_URL/HA_TOKEN from light_lib rather than restating the token:
it is already hardcoded in six tracked files in a public repo (that is a known issue,
tracked separately) and this file will not be the seventh.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from light_lib import HA_URL, HA_TOKEN  # noqa: E402

# Friendly name -> HA notify service. `jeff` is the default target.
TARGETS = {
    "jeff": "mobile_app_jeff_pix10",
    "ipad": "mobile_app_jeff_hayes_s_ipad_air3",
    "carol": "mobile_app_carol_pix10",
    "desktop": "jeff_desktop",
}


def send(message, title="Caia", target="jeff", wake=False, tag=None,
         channel=None, timeout=15):
    """POST one notification. Returns (ok, detail).

    NOTE ON WHAT THE RETURN VALUE MEANS: True == Home Assistant accepted the service
    call. It does NOT prove the handset rang; that round trip is not observable from
    here. This is the exact distinction that made notify.py's `resp.status == 200` look
    like success for months while nothing was subscribed. Do not report a True from this
    function as "Jeff was notified" — report it as "HA accepted it".
    """
    service = TARGETS.get(target)
    if service is None:
        return False, f"unknown target {target!r}; known: {', '.join(sorted(TARGETS))}"

    # MEASURED 2026-09-18 against Jeff's actual handset, because HA returns 200 either way
    # and the two cases are indistinguishable from here:
    #   {"channel": "caia", "importance": "default"}      -> HTTP 200, NEVER ARRIVED
    #   {"priority": "high", "ttl": 0}                     -> arrives (normal ding)
    #   {"channel": "alarm_stream", "priority": "high", ...} -> arrives, rings through DND
    # The first one failed because without priority/ttl the push is an FCM NORMAL-priority
    # message, which Android's Doze is entitled to defer indefinitely on an idle phone --
    # and a custom channel the app has not been configured for gets no help either. So
    # priority=high + ttl=0 is the FLOOR for anything that must actually land, not an
    # escalation. A notification that only sometimes arrives is worse than none, because
    # its silence reads as "nothing happened".
    data = {"priority": "high", "ttl": 0}
    if wake:
        # alarm_stream is the DND bypass on the Android companion app. Rings on the alarm
        # stream rather than the notification stream -- confirmed audibly, Jeff's words:
        # "a lot more attention getting than a soft ding."
        data.update({"channel": "alarm_stream", "importance": "high"})
    if channel and not wake:
        data["channel"] = channel
    if tag:
        # A stable tag lets a later send REPLACE this notification instead of stacking
        # another one up — right for a recurring watchdog that would otherwise spam.
        data["tag"] = tag

    body = json.dumps({"title": title, "message": message, "data": data}).encode()
    req = urllib.request.Request(
        f"{HA_URL}/api/services/notify/{service}",
        data=body, method="POST",
        headers={"Authorization": f"Bearer {HA_TOKEN}",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return True, f"HA accepted (HTTP {resp.status}) -> notify.{service}"
    except urllib.error.HTTPError as e:
        return False, f"HA refused: HTTP {e.code} {e.reason}"
    except Exception as e:  # URLError, timeout, DNS, HA down
        return False, f"could not reach HA at {HA_URL}: {e}"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("message", nargs="?", help="notification body")
    ap.add_argument("--title", default="Caia")
    ap.add_argument("--to", default="jeff", choices=sorted(TARGETS))
    ap.add_argument("--wake", action="store_true",
                    help="alarm channel - bypasses Do Not Disturb. For real need only.")
    ap.add_argument("--channel", help="custom Android notification channel (opt-in; an "
                    "unconfigured channel silently swallowed a test message)")
    ap.add_argument("--tag", help="stable id; a later send with the same tag replaces this one")
    ap.add_argument("--list", action="store_true", help="show known targets and exit")
    args = ap.parse_args()

    if args.list:
        for name, svc in sorted(TARGETS.items()):
            print(f"  {name:8} -> notify.{svc}")
        return 0
    if not args.message:
        ap.error("a message is required (or use --list)")

    ok, detail = send(args.message, title=args.title, target=args.to,
                      wake=args.wake, tag=args.tag, channel=args.channel)
    # Print on BOTH paths. notify.py printed nothing on success, so an eaten exit code
    # read as silence-means-fine. Silence should never be the success signal.
    print(detail, file=sys.stdout if ok else sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
