"""
Todoist REST API v2 poller.

Auth: personal API token (Settings -> Integrations -> Developer in Todoist),
no OAuth dance needed. Put it in .env as TODOIST_API_TOKEN.

We ask Todoist to do the date filtering for us via its filter query
language (`overdue | today | 3 days`) rather than pulling every task and
filtering client-side - cheaper for both sides on a low-power box.
Docs: https://developer.todoist.com/rest/v2/#get-active-tasks
"""
from __future__ import annotations

import datetime as dt
from typing import Any

import httpx

from .base import Poller

API_BASE = "https://api.todoist.com/rest/v2"


class TodoistPoller(Poller):
    name = "todoist"

    def __init__(self, interval_seconds: float, token: str, upcoming_days: int = 3,
                 filter_override: str | None = None):
        super().__init__(interval_seconds)
        self._token = token
        self._upcoming_days = upcoming_days
        self._filter_override = filter_override
        self._client: httpx.AsyncClient | None = None

    async def setup(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=API_BASE,
            headers={"Authorization": f"Bearer {self._token}"},
            timeout=10.0,
        )

    async def teardown(self) -> None:
        if self._client:
            await self._client.aclose()

    def _filter_query(self) -> str:
        if self._filter_override:
            return self._filter_override
        parts = ["overdue", "today"]
        if self._upcoming_days > 0:
            parts.append(f"{self._upcoming_days} days")
        return " | ".join(parts)

    async def fetch(self) -> dict[str, Any]:
        if not self._client:
            raise RuntimeError("todoist client not initialized")

        resp = await self._client.get("/tasks", params={"filter": self._filter_query()})
        resp.raise_for_status()
        tasks = resp.json()

        today = dt.date.today()
        overdue: list[dict] = []
        due_today: list[dict] = []
        upcoming: list[dict] = []

        for t in tasks:
            due = t.get("due") or {}
            due_date_str = due.get("date")  # "YYYY-MM-DD" or full datetime for timed tasks
            shaped = {
                "id": t.get("id"),
                "content": t.get("content"),
                "priority": t.get("priority"),  # 1 (normal) - 4 (urgent)
                "due_date": due_date_str,
                "due_string": due.get("string"),
                "is_recurring": bool(due.get("is_recurring")),
                "url": t.get("url"),
            }
            if not due_date_str:
                upcoming.append(shaped)
                continue
            due_date = due_date_str[:10]
            try:
                parsed = dt.date.fromisoformat(due_date)
            except ValueError:
                upcoming.append(shaped)
                continue
            if parsed < today:
                overdue.append(shaped)
            elif parsed == today:
                due_today.append(shaped)
            else:
                upcoming.append(shaped)

        sort_key = lambda t: (t["due_date"] or "", -(t["priority"] or 0))
        overdue.sort(key=sort_key)
        due_today.sort(key=sort_key)
        upcoming.sort(key=sort_key)

        return {"overdue": overdue, "today": due_today, "upcoming": upcoming}
