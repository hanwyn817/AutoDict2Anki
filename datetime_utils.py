from datetime import datetime, timezone
from typing import Optional

FALLBACK_DATETIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S.%f",
)


def normalize_datetime(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def parse_datetime_flexible(value: str) -> Optional[datetime]:
    if value is None:
        return None

    raw = str(value).strip()
    if not raw:
        return None

    normalized = raw.replace("/", "-")
    candidates = {raw, normalized}

    if normalized.endswith("Z"):
        candidates.add(normalized[:-1] + "+00:00")
        candidates.add(normalized[:-1] + " +00:00")

    if "T" in normalized:
        candidates.add(normalized.replace("T", " "))
    elif " " in normalized:
        candidates.add(normalized.replace(" ", "T"))

    for candidate in candidates:
        try:
            return normalize_datetime(datetime.fromisoformat(candidate))
        except ValueError:
            continue

    for fmt in FALLBACK_DATETIME_FORMATS:
        try:
            return datetime.strptime(normalized, fmt)
        except ValueError:
            continue

    return None


def format_datetime_for_storage(dt: datetime) -> str:
    return normalize_datetime(dt).strftime("%Y-%m-%d %H:%M:%S")
