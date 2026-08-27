"""
CalDAV calendar poller. Fastmail is the primary target (app-password auth,
no OAuth), but this speaks plain CalDAV so it works unmodified against
iCloud too - just point CALDAV_URL/CALDAV_USERNAME/CALDAV_APP_PASSWORD at
Apple's endpoint and use an app-specific password from appleid.apple.com.
See README for the exact URLs/known gotchas for each provider.

The `caldav` library is synchronous, so every call in here runs inside
`asyncio.to_thread()` to avoid blocking the event loop - acceptable given
the poll interval is measured in minutes, not seconds.
"""
from __future__ import annotations

import asyncio
import datetime as dt
from typing import Any

import caldav

from .base import Poller


class CalendarPoller(Poller):
    name = "calendar"

    def __init__(self, interval_seconds: float, url: str, username: str, password: str,
                 calendar_names: list[str] | None = None, lookahead_days: int = 3):
        super().__init__(interval_seconds)
        self._url = url
        self._username = username
        self._password = password
        self._calendar_names = set(calendar_names or [])
        self._lookahead_days = lookahead_days

    def _fetch_sync(self) -> dict[str, Any]:
        client = caldav.DAVClient(url=self._url, username=self._username, password=self._password)
        principal = client.principal()
        calendars = principal.calendars()

        if self._calendar_names:
            calendars = [c for c in calendars if c.name in self._calendar_names]

        now = dt.datetime.now().astimezone()
        start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        window_end = start_of_today + dt.timedelta(days=self._lookahead_days)

        events: list[dict] = []
        for calendar in calendars:
            try:
                results = calendar.date_search(start=start_of_today, end=window_end, expand=True)
            except Exception:
                # A single misbehaving calendar shouldn't blank the whole panel.
                continue
            for item in results:
                for vevent in getattr(item.icalendar_instance, "walk", lambda *_: [])("VEVENT"):
                    events.append(_shape_event(vevent, calendar.name))

        events.sort(key=lambda e: e["start"])

        today_events = [e for e in events if e["date"] == now.date().isoformat()]

        next_event = None
        for e in events:
            if e["start_dt"] is not None and e["start_dt"] >= now:
                next_event = e
                break

        for e in events:
            e.pop("start_dt", None)

        return {"today": today_events, "next_event": next_event}

    async def fetch(self) -> dict[str, Any]:
        return await asyncio.to_thread(self._fetch_sync)


def _shape_event(vevent, calendar_name: str) -> dict[str, Any]:
    summary = str(vevent.get("summary", "")) if vevent.get("summary") else "(no title)"
    dtstart = vevent.get("dtstart").dt if vevent.get("dtstart") else None
    dtend = vevent.get("dtend").dt if vevent.get("dtend") else None
    location = str(vevent.get("location", "")) if vevent.get("location") else None

    all_day = isinstance(dtstart, dt.date) and not isinstance(dtstart, dt.datetime)

    start_dt = None
    if isinstance(dtstart, dt.datetime):
        start_dt = dtstart if dtstart.tzinfo else dtstart.astimezone()
        date_str = start_dt.date().isoformat()
        start_str = start_dt.isoformat()
    elif isinstance(dtstart, dt.date):
        date_str = dtstart.isoformat()
        start_str = date_str
        start_dt = dt.datetime.combine(dtstart, dt.time.min).astimezone()
    else:
        date_str = ""
        start_str = ""

    end_str = None
    if isinstance(dtend, (dt.date, dt.datetime)):
        end_str = dtend.isoformat()

    return {
        "summary": summary,
        "date": date_str,
        "start": start_str,
        "start_dt": start_dt,
        "end": end_str,
        "all_day": all_day,
        "location": location,
        "calendar": calendar_name,
    }
