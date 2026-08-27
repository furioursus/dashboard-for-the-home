"""
Philips Hue local bridge poller/controller.

Uses the classic local v1 API (https://<bridge-ip>/api/<key>/...). It's
officially in "legacy" status in favor of CLIP v2, but it's still fully
functional on current bridge firmware, has a much simpler JSON shape, and
needs no SSE/event-stream handling for a simple poll-every-few-seconds
dashboard - a reasonable tradeoff for a prototype. If Signify ever pulls
the plug on v1, this is the one module that would need porting to v2
(GET/PUT https://<bridge-ip>/clip/v2/resource/grouped_light/<id>).

Pairing (one-time, can't be done headless without a human at the bridge):
press the physical link button on the bridge, then POST to /api with a
devicetype within ~30s. See setup/pair_hue.py for a small helper script,
and the README for the manual walkthrough.

The bridge serves a self-signed cert, so we disable TLS verification for
this client only - it never leaves the LAN.
"""
from __future__ import annotations

from typing import Any

import httpx

from .base import Poller

# Hue brightness ("bri") is 1-254 internally; we expose 1-100% to the API
# and frontend because nobody wants to think in 254ths.
_HUE_BRI_MAX = 254


def _bri_to_percent(bri: int) -> int:
    return max(1, round((bri / _HUE_BRI_MAX) * 100))


def _percent_to_bri(percent: int) -> int:
    percent = max(1, min(100, percent))
    return max(1, round((percent / 100) * _HUE_BRI_MAX))


class HuePoller(Poller):
    name = "hue"

    def __init__(self, interval_seconds: float, bridge_ip: str, api_key: str, group_id: str):
        super().__init__(interval_seconds)
        self._bridge_ip = bridge_ip
        self._api_key = api_key
        self._group_id = str(group_id)
        self._client: httpx.AsyncClient | None = None

    async def setup(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=f"https://{self._bridge_ip}",
            verify=False,
            timeout=5.0,
        )

    async def teardown(self) -> None:
        if self._client:
            await self._client.aclose()

    def _group_path(self) -> str:
        return f"/api/{self._api_key}/groups/{self._group_id}"

    async def fetch(self) -> dict[str, Any]:
        if not self._client:
            raise RuntimeError("hue client not initialized")
        resp = await self._client.get(self._group_path())
        resp.raise_for_status()
        body = resp.json()
        if isinstance(body, list) and body and "error" in body[0]:
            raise RuntimeError(body[0]["error"].get("description", "Hue bridge error"))
        return self._shape(body)

    def _shape(self, group: dict) -> dict[str, Any]:
        action = group.get("action", {})
        state = group.get("state", {})
        return {
            "name": group.get("name"),
            "on": bool(action.get("on", False)),
            "brightness": _bri_to_percent(action.get("bri", _HUE_BRI_MAX)),
            "any_on": bool(state.get("any_on", False)),
            "all_on": bool(state.get("all_on", False)),
        }

    async def set_power(self, on: bool) -> dict[str, Any]:
        """Called directly from the API route (not the poll loop) so a touch
        on the panel feels instant instead of waiting for the next cycle."""
        if not self._client:
            raise RuntimeError("hue client not initialized")
        resp = await self._client.put(f"{self._group_path()}/action", json={"on": on})
        resp.raise_for_status()
        return await self.fetch()

    async def set_brightness(self, percent: int) -> dict[str, Any]:
        if not self._client:
            raise RuntimeError("hue client not initialized")
        bri = _percent_to_bri(percent)
        resp = await self._client.put(f"{self._group_path()}/action", json={"on": True, "bri": bri})
        resp.raise_for_status()
        return await self.fetch()
