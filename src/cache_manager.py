"""Simple file-based cache for generated FSDs."""
import json
import os
from pathlib import Path
from datetime import datetime

CACHE_DIR = Path("cache")
CACHE_DIR.mkdir(exist_ok=True)


def _cache_path(key: str) -> Path:
    safe = key.lower().replace(" ", "_").replace("/", "_")
    return CACHE_DIR / f"{safe}.json"


def get_cache(key: str) -> dict | None:
    path = _cache_path(key)
    if path.exists():
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            return None
    return None


def set_cache(key: str, data: dict) -> None:
    path = _cache_path(key)
    try:
        data["cached_at"] = datetime.utcnow().isoformat()
        with open(path, "w") as f:
            json.dump(data, f)
    except Exception:
        pass


def cache_age_label(key: str) -> str:
    path = _cache_path(key)
    if not path.exists():
        return ""
    try:
        with open(path) as f:
            data = json.load(f)
        cached_at = data.get("cached_at", "")
        if cached_at:
            dt = datetime.fromisoformat(cached_at)
            delta = datetime.utcnow() - dt
            days = delta.days
            if days == 0:
                return "cached today"
            elif days == 1:
                return "cached yesterday"
            else:
                return f"cached {days} days ago"
    except Exception:
        pass
    return "cached"
