"""
Curated icon keys allowed in tenant settings (e.g. `services_page.services[].icon`).

The frontend mirrors this list in `frontend/src/lib/icon-registry.ts`, so the
settings icon picker and the public Services page always agree. Keys are
lowercase lucide-react names; legacy values are accepted case-insensitively.
"""

from typing import FrozenSet, Optional

ALLOWED_ICON_KEYS: FrozenSet[str] = frozenset(
    {
        "truck",
        "plane",
        "train",
        "ship",
        "warehouse",
        "package",
        "boxes",
        "shopping-cart",
        "refresh-ccw",
        "clock",
        "shield-check",
        "snowflake",
        "store",
        "factory",
        "globe",
        "bike",
        "map-pin",
        "file-text",
    }
)


def normalize_icon_key(raw: Optional[str]) -> Optional[str]:
    """
    Canonical (lowercase, trimmed) icon key, or None when not in the registry.

    Args:
        raw: The stored / submitted icon value (legacy values may be "Truck").
    """
    if raw is None:
        return None
    key = raw.strip().lower()
    return key if key in ALLOWED_ICON_KEYS else None
