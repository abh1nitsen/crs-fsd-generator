"""Curated source-registry freshness helpers.

These helpers deliberately do not fetch or rewrite official guidance during a
user generation run. They summarize registered source metadata so the UI/DOCX
can tell users whether local facts are curated, stale, or need review.
"""
from __future__ import annotations

from datetime import date
from typing import Any


def _safe_text(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text or fallback


def _parse_iso(value: Any) -> date | None:
    text = _safe_text(value)
    if not text or text.lower() in {"not checked", "not recorded", "not_checked_in_runtime"}:
        return None
    try:
        return date.fromisoformat(text[:10])
    except Exception:
        return None


def freshness_from_registry(registry: dict[str, Any], *, today: date | None = None) -> dict[str, str]:
    """Return user-facing source freshness metadata from a source registry.

    This is metadata-only. It does not call the network and does not mutate KB
    facts. Human review is still required before changing implementation facts.
    """
    today = today or date.today()
    sources = registry.get("sources") if isinstance(registry.get("sources"), list) else []
    dates: list[date] = []
    for src in sources:
        if isinstance(src, dict):
            parsed = _parse_iso(src.get("last_verified") or src.get("fetched_at") or src.get("last_checked"))
            if parsed:
                dates.append(parsed)
    top_level_date = _parse_iso(registry.get("last_verified") or registry.get("last_checked"))
    if top_level_date:
        dates.append(top_level_date)

    if dates:
        last_verified = max(dates)
        age_days = max(0, (today - last_verified).days)
        if age_days <= 45:
            status = "Fresh"
        elif age_days <= 120:
            status = "Review soon"
        else:
            status = "Stale - review recommended"
        last_verified_text = last_verified.isoformat()
    else:
        status = _safe_text(registry.get("source_freshness"), "Not checked")
        age_days = -1
        last_verified_text = _safe_text(registry.get("last_verified"), "Not recorded")

    return {
        "status": status,
        "last_verified": last_verified_text,
        "age_days": str(age_days) if age_days >= 0 else "Unknown",
        "refresh_frequency": _safe_text(registry.get("refresh_frequency"), "Weekly source availability checks; human review before fact updates"),
        "refresh_mode": _safe_text(registry.get("kb_refresh_mode"), "Curated registry; no runtime fact rewrite"),
        "user_message": _safe_text(
            registry.get("user_message"),
            "Generation uses curated KB facts. Re-check registered official sources before production configuration.",
        ),
    }
