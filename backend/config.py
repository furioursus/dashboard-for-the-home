"""
Loads settings from two places, per the split described in the README:

- .env          -> secrets + machine-specific network info (API tokens,
                    CalDAV creds, Hue bridge IP/key, Bambu IP/access code).
                    Gitignored, never committed.
- config.yaml   -> room-specific, non-secret settings (which Hue group to
                    control, display names, poll intervals). This is the
                    file a future "clone this for the living room" install
                    actually edits.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(
            f"Missing {path}. Copy config.yaml.example to config.yaml and edit it."
        )
    with open(path) as f:
        return yaml.safe_load(f) or {}


_config_path = Path(os.environ.get("DASHBOARD_CONFIG", BASE_DIR / "config.yaml"))
CONFIG: dict[str, Any] = _load_yaml(_config_path)


def cfg(*keys: str, default: Any = None) -> Any:
    """Nested config.yaml lookup: cfg('polling', 'hue_seconds', default=7)."""
    node: Any = CONFIG
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return node


def env(key: str, default: str | None = None, required: bool = False) -> str | None:
    val = os.environ.get(key, default)
    if required and not val:
        raise RuntimeError(
            f"Missing required environment variable: {key}. "
            f"Copy .env.example to .env and fill it in."
        )
    return val
