"""
Bambu Lab P1S local status via the printer's LAN-only MQTT broker.

*** Uncertainty flag (read before trusting this in production) ***
Bambu has never published this protocol. Everything below is reconstructed
from community reverse-engineering - primarily cross-checked against
Home Assistant's `bambu_lab` integration
(https://github.com/greghesp/ha-bambulab) and the `bambulabs_api` PyPI
package (https://github.com/mathias-boulay/bambulabs_api /
https://github.com/acryptohash/bambulabs_api - there are a couple of forks,
check which is current). Field names, the exact "pushall" request shape,
and TLS behavior have all changed across printer firmware versions before.
If this doesn't connect or the field names below come back empty:
  1. Confirm LAN Only Mode is ON in the printer's network settings and you
     have the current Access Code (Settings > WLAN on the P1S touchscreen).
  2. Try `pip install bambulabs_api` and use its client directly instead of
     hand-rolling the MQTT parsing here - it's actively maintained and
     tracks firmware changes; swapping it in only requires changing this
     one file, the Poller interface above doesn't care how fetch() gets
     its data.
  3. Watch the raw MQTT traffic with `mosquitto_sub` (see README) against
     `device/<serial>/report` to see what your firmware is actually
     sending and adjust `_parse_report` accordingly.

Protocol as reverse-engineered:
- Broker: mqtts://<printer-ip>:8883, self-signed cert (verify disabled).
- Username: "bambulocal", password: the Access Code from the printer.
- Subscribe: device/<serial>/report - printer pushes state changes here
  on its own; no need to poll it like a REST API.
- To force a fresh full report on connect, publish to
  device/<serial>/request: {"pushing": {"sequence_id": "0", "command": "pushall"}}
- Payloads are JSON with a top-level "print" object containing the fields
  we care about (gcode_state, mc_percent, mc_remaining_time, subtask_name,
  bed_temper, nozzle_temper, bed_target_temper, nozzle_target_temper).

paho-mqtt's client is callback-driven and runs its own network thread
(`loop_start()`), so unlike the other pollers this one doesn't really
"fetch" on each cycle - MQTT pushes updates as they happen. `fetch()`
just hands back whatever the callback thread last stored, and the
scheduled poll cycle doubles as a periodic "pushall" nudge so a dropped
message doesn't leave the panel stale forever.
"""
from __future__ import annotations

import json
import ssl
import threading
import time
from typing import Any

import paho.mqtt.client as mqtt

from .base import Poller

REQUEST_TOPIC = "device/{serial}/request"
REPORT_TOPIC = "device/{serial}/report"

_STATE_MAP = {
    "IDLE": "idle",
    "FINISH": "idle",
    "RUNNING": "printing",
    "PREPARE": "printing",
    "SLICING": "printing",
    "PAUSE": "paused",
    "FAILED": "error",
}


class BambuPoller(Poller):
    name = "bambu"

    def __init__(self, interval_seconds: float, printer_ip: str, access_code: str, serial: str):
        super().__init__(interval_seconds)
        self._ip = printer_ip
        self._access_code = access_code
        self._serial = serial
        self._client: mqtt.Client | None = None
        self._connected = threading.Event()
        self._latest: dict[str, Any] = {}
        self._state_lock = threading.Lock()

    async def setup(self) -> None:
        client = mqtt.Client(client_id="office-pi-dashboard", protocol=mqtt.MQTTv311)
        client.username_pw_set("bambulocal", self._access_code)
        client.tls_set(cert_reqs=ssl.CERT_NONE)
        client.tls_insecure_set(True)
        client.on_connect = self._on_connect
        client.on_message = self._on_message
        client.on_disconnect = self._on_disconnect

        client.connect_async(self._ip, 8883, keepalive=30)
        client.loop_start()
        self._client = client

    async def teardown(self) -> None:
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()

    def _on_connect(self, client, userdata, flags, rc):
        if rc != 0:
            return
        self._connected.set()
        client.subscribe(REPORT_TOPIC.format(serial=self._serial))
        self._request_pushall(client)

    def _on_disconnect(self, client, userdata, rc):
        self._connected.clear()

    def _request_pushall(self, client) -> None:
        payload = json.dumps({"pushing": {"sequence_id": "0", "command": "pushall"}})
        client.publish(REQUEST_TOPIC.format(serial=self._serial), payload)

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return
        print_block = payload.get("print")
        if not isinstance(print_block, dict):
            return
        with self._state_lock:
            self._latest.update(print_block)

    async def fetch(self) -> dict[str, Any]:
        if not self._connected.is_set():
            raise RuntimeError(f"not connected to Bambu printer at {self._ip}")

        # Nudge a full resync each cycle in case a delta message was missed -
        # cheap over LAN MQTT, and keeps a stuck panel from lying silently.
        if self._client:
            self._request_pushall(self._client)

        with self._state_lock:
            raw = dict(self._latest)

        if not raw:
            # Connected but haven't received a report yet (e.g. just booted).
            return {"connected": True, "state": "unknown"}

        return self._parse_report(raw)

    def _parse_report(self, raw: dict) -> dict[str, Any]:
        gcode_state = str(raw.get("gcode_state", "")).upper()
        remaining = raw.get("mc_remaining_time")  # minutes, per observed firmware
        eta = None
        if isinstance(remaining, (int, float)) and remaining >= 0:
            eta = time.time() + remaining * 60

        return {
            "connected": True,
            "state": _STATE_MAP.get(gcode_state, "unknown"),
            "raw_state": gcode_state or None,
            "task_name": raw.get("subtask_name") or None,
            "progress_percent": raw.get("mc_percent"),
            "remaining_minutes": remaining,
            "eta_epoch": eta,
            "bed_temp": raw.get("bed_temper"),
            "bed_target": raw.get("bed_target_temper"),
            "nozzle_temp": raw.get("nozzle_temper"),
            "nozzle_target": raw.get("nozzle_target_temper"),
        }
