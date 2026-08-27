"""
Shared base class for every integration poller.

Design goals (matter a lot on a 512MB Pi Zero 2 W):
- One long-lived asyncio task per integration, each on its own interval.
  No thread pools, no per-request client construction.
- Never let one bad poll take the panel down. On error we keep serving the
  last good `data` and just attach an `error` string + `error_since`
  timestamp, so the frontend can show "stale" instead of blanking a panel.
- `snapshot()` is called very frequently (once per /api/state request, and
  the frontend polls that every few seconds) so it must be cheap and
  non-blocking - it just reads already-computed state, it never triggers
  a fetch itself.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger("dashboard")


class Poller:
    """Base class for a background polling integration.

    Subclasses implement `fetch()` (async, returns a JSON-serializable dict)
    and set `name`. Everything else (the loop, error handling, snapshotting)
    is handled here so each integration module stays focused on just talking
    to its API.
    """

    name = "base"

    def __init__(self, interval_seconds: float):
        self.interval = interval_seconds
        self._data: Any = None
        self._updated_at: float | None = None
        self._error: str | None = None
        self._error_since: float | None = None
        self._lock = asyncio.Lock()
        self._stop = asyncio.Event()

    async def fetch(self) -> Any:
        raise NotImplementedError

    async def setup(self) -> None:
        """Optional one-time async setup (open a connection, etc.). Override
        if needed; default is a no-op."""
        return None

    async def teardown(self) -> None:
        """Optional cleanup on shutdown. Override if needed."""
        return None

    async def run_forever(self) -> None:
        try:
            await self.setup()
        except Exception as exc:  # setup failures shouldn't kill the process
            logger.exception("%s: setup failed: %s", self.name, exc)

        while not self._stop.is_set():
            cycle_start = time.monotonic()
            try:
                data = await self.fetch()
                async with self._lock:
                    self._data = data
                    self._updated_at = time.time()
                    self._error = None
                    self._error_since = None
            except Exception as exc:
                logger.warning("%s: poll failed: %s", self.name, exc)
                async with self._lock:
                    self._error = str(exc)
                    if self._error_since is None:
                        self._error_since = time.time()

            elapsed = time.monotonic() - cycle_start
            sleep_for = max(0.5, self.interval - elapsed)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=sleep_for)
            except asyncio.TimeoutError:
                pass

        await self.teardown()

    def stop(self) -> None:
        self._stop.set()

    async def set_data(self, data: Any) -> None:
        """Let a direct-action route (e.g. a touch on the Hue toggle) push a
        fresh value into the cache immediately, instead of waiting for the
        next scheduled poll to pick it up."""
        async with self._lock:
            self._data = data
            self._updated_at = time.time()
            self._error = None
            self._error_since = None

    async def snapshot(self) -> dict:
        async with self._lock:
            return {
                "data": self._data,
                "updated_at": self._updated_at,
                "error": self._error,
                "error_since": self._error_since,
            }
