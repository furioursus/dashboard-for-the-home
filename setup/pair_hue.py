#!/usr/bin/env python3
"""
One-time Hue bridge pairing helper (the "press-link" flow).

The Hue bridge only hands out a local API key within ~30s of someone
physically pressing the button on top of it - this can't be automated
away, but this script makes the API dance painless: run it, press the
button when it tells you to, and it prints the values to put in .env.

Stdlib only (no dependency on the backend's venv) so it can be run
straight from a fresh Pi OS Lite install before anything else is set up.

Usage:
    python3 pair_hue.py <bridge-ip>

If you don't know your bridge's IP, check your router's DHCP client list
for "Philips-hue", or (from a machine on the same LAN) try Signify's cloud
discovery endpoint: https://discovery.meethue.com/
"""
from __future__ import annotations

import json
import ssl
import sys
import time
import urllib.error
import urllib.request

DEVICETYPE = "office-pi-dashboard#kiosk"
ATTEMPTS = 30
DELAY_SECONDS = 2

# The bridge serves a self-signed cert - fine to skip verification here,
# this is a one-time LAN-only pairing request.
_INSECURE_CTX = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
_INSECURE_CTX.check_hostname = False
_INSECURE_CTX.verify_mode = ssl.CERT_NONE


def request_pairing(bridge_ip: str) -> list | dict:
    url = f"https://{bridge_ip}/api"
    payload = json.dumps({"devicetype": DEVICETYPE}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST",
                                  headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5, context=_INSECURE_CTX) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <bridge-ip>")
        return 1
    bridge_ip = sys.argv[1]

    print(f"Bridge: {bridge_ip}")
    print("Press the physical link button on the Hue bridge now.")
    print(f"Waiting up to {ATTEMPTS * DELAY_SECONDS}s for it...\n")

    for attempt in range(1, ATTEMPTS + 1):
        try:
            body = request_pairing(bridge_ip)
        except (urllib.error.URLError, TimeoutError) as exc:
            print(f"[{attempt}] request failed: {exc}")
            time.sleep(DELAY_SECONDS)
            continue

        entry = body[0] if isinstance(body, list) and body else {}
        if "success" in entry:
            username = entry["success"]["username"]
            print("\nPaired! Add these to your .env:\n")
            print(f"HUE_BRIDGE_IP={bridge_ip}")
            print(f"HUE_API_KEY={username}")
            return 0

        error = entry.get("error", {})
        if error.get("type") == 101:  # link button not pressed yet
            print(f"[{attempt}] link button not pressed yet, waiting...")
        else:
            print(f"[{attempt}] bridge error: {error}")
        time.sleep(DELAY_SECONDS)

    print("\nTimed out waiting for the link button. Run again and press it sooner.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
