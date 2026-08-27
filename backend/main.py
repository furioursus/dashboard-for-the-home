"""
Office Pi Dashboard backend.

Serves the single-page frontend and a small JSON API that the page polls.
Each integration runs as its own background asyncio task at its own
interval (see pollers/base.py); this module just wires them up and exposes
their cached state, plus the couple of write endpoints Hue control needs.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from config import CONFIG, cfg, env
from pollers.bambu import BambuPoller
from pollers.calendar import CalendarPoller
from pollers.hue import HuePoller
from pollers.todoist import TodoistPoller

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("dashboard")

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"

POLLERS: dict[str, Any] = {}
_background_tasks: list[asyncio.Task] = []


def _build_pollers() -> dict[str, Any]:
    pollers: dict[str, Any] = {}

    pollers["todoist"] = TodoistPoller(
        interval_seconds=cfg("polling", "todoist_seconds", default=180),
        token=env("TODOIST_API_TOKEN", required=True),
        upcoming_days=cfg("todoist", "upcoming_days", default=3),
        filter_override=cfg("todoist", "filter", default="") or None,
    )

    pollers["calendar"] = CalendarPoller(
        interval_seconds=cfg("polling", "calendar_seconds", default=900),
        url=env("CALDAV_URL", required=True),
        username=env("CALDAV_USERNAME", required=True),
        password=env("CALDAV_APP_PASSWORD", required=True),
        calendar_names=cfg("calendar", "calendar_names", default=[]),
        lookahead_days=cfg("calendar", "lookahead_days", default=3),
    )

    pollers["hue"] = HuePoller(
        interval_seconds=cfg("polling", "hue_seconds", default=7),
        bridge_ip=env("HUE_BRIDGE_IP", required=True),
        api_key=env("HUE_API_KEY", required=True),
        group_id=cfg("hue", "group_id", default="1"),
    )

    pollers["bambu"] = BambuPoller(
        interval_seconds=cfg("polling", "bambu_seconds", default=5),
        printer_ip=env("BAMBU_IP", required=True),
        access_code=env("BAMBU_ACCESS_CODE", required=True),
        serial=env("BAMBU_SERIAL", required=True),
    )

    return pollers


@asynccontextmanager
async def lifespan(app: FastAPI):
    POLLERS.update(_build_pollers())
    for poller in POLLERS.values():
        _background_tasks.append(asyncio.create_task(poller.run_forever()))
    logger.info("started %d pollers: %s", len(POLLERS), ", ".join(POLLERS))

    yield

    for poller in POLLERS.values():
        poller.stop()
    for task in _background_tasks:
        task.cancel()
    await asyncio.gather(*_background_tasks, return_exceptions=True)


app = FastAPI(title="Office Pi Dashboard", lifespan=lifespan)


@app.get("/api/state")
async def get_state():
    panels = {name: await poller.snapshot() for name, poller in POLLERS.items()}
    return {
        "room": {
            "display_name": cfg("room", "display_name", default="Room"),
        },
        "panels": panels,
    }


class PowerRequest(BaseModel):
    on: bool


class BrightnessRequest(BaseModel):
    percent: int = Field(ge=1, le=100)


@app.post("/api/hue/power")
async def hue_power(req: PowerRequest):
    hue: HuePoller = POLLERS.get("hue")
    if not hue:
        raise HTTPException(503, "hue poller not ready")
    try:
        data = await hue.set_power(req.on)
    except Exception as exc:
        raise HTTPException(502, f"failed to reach Hue bridge: {exc}") from exc
    await hue.set_data(data)
    return data


@app.post("/api/hue/brightness")
async def hue_brightness(req: BrightnessRequest):
    hue: HuePoller = POLLERS.get("hue")
    if not hue:
        raise HTTPException(503, "hue poller not ready")
    try:
        data = await hue.set_brightness(req.percent)
    except Exception as exc:
        raise HTTPException(502, f"failed to reach Hue bridge: {exc}") from exc
    await hue.set_data(data)
    return data


# Static frontend last, so /api/* above always wins.
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/")
async def index():
    return FileResponse(FRONTEND_DIR / "index.html")


if __name__ == "__main__":
    # `python main.py` for local dev; the systemd unit in setup/ invokes
    # uvicorn directly instead, but reads the same config.yaml values.
    import uvicorn

    uvicorn.run(
        "main:app",
        host=cfg("server", "host", default="0.0.0.0"),
        port=cfg("server", "port", default=5000),
    )
