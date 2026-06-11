"""Utility helpers for the api-service-handler library.

Provides common helper functions used across the library including
ID generation, date/time utilities, string masking, connection string
validation, metadata filtering, and more.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator
from datetime import date, datetime, timedelta, timezone
from typing import Any


def generate_id() -> str:
    """Generate a new UUID4 string.

    Returns:
        A lowercase hex UUID4 string (e.g. ``'a1b2c3d4-...'``).
    """
    return str(uuid.uuid4())


def now_utc() -> datetime:
    """Return the current UTC datetime (timezone-aware).

    Returns:
        A :class:`datetime.datetime` with ``tzinfo`` set to :data:`datetime.timezone.utc`.
    """
    return datetime.now(tz=timezone.utc)


def today_utc() -> date:
    """Return the current UTC date.

    Returns:
        A :class:`datetime.date` representing today in UTC.
    """
    return now_utc().date()


def is_same_day(d1: date, d2: date) -> bool:
    """Check whether two dates represent the same calendar day.

    Args:
        d1: First date.
        d2: Second date.

    Returns:
        ``True`` if *d1* and *d2* have the same year, month, and day.
    """
    return d1.year == d2.year and d1.month == d2.month and d1.day == d2.day


def is_same_month(d1: date, d2: date) -> bool:
    """Check whether two dates fall in the same month and year.

    Args:
        d1: First date.
        d2: Second date.

    Returns:
        ``True`` if *d1* and *d2* share the same year and month.
    """
    return d1.year == d2.year and d1.month == d2.month


def mask_key_value(key: str, visible_chars: int = 8) -> str:
    """Mask a sensitive string, showing only leading characters.

    If *key* is shorter than *visible_chars*, the first 2 characters are
    shown followed by ``'***'``.  Otherwise the first *visible_chars*
    characters are shown followed by ``'***'``.

    Args:
        key: The sensitive string to mask.
        visible_chars: Number of leading characters to keep visible.
            Defaults to ``8``.

    Returns:
        The masked string.

    Examples:
        >>> mask_key_value("sk-abc123456789")
        'sk-abc12***'
        >>> mask_key_value("short")
        'sh***'
    """
    if not key:
        return "***"

    if len(key) < visible_chars:
        return key[:2] + "***"

    return key[:visible_chars] + "***"


# ---------------------------------------------------------------------------
# Connection-string validation
# ---------------------------------------------------------------------------

_BACKEND_PREFIXES: dict[str, list[str]] = {
    "sqlite": ["sqlite:///", "sqlite://"],
    "mongo": ["mongodb://", "mongodb+srv://"],
    "mongodb": ["mongodb://", "mongodb+srv://"],
    "pg": ["postgresql://", "postgresql+asyncpg://", "postgres://"],
    "postgres": ["postgresql://", "postgresql+asyncpg://", "postgres://"],
    "postgresql": ["postgresql://", "postgresql+asyncpg://", "postgres://"],
}


def validate_connection_string(backend: str, connection_string: str) -> bool:
    """Validate that a connection string format matches the given backend.

    Performs a basic prefix check — it does **not** attempt to connect or
    parse every component of the URI.

    Supported backends (case-insensitive):

    * ``sqlite`` — expects ``sqlite://``
    * ``mongo`` / ``mongodb`` — expects ``mongodb://`` or ``mongodb+srv://``
    * ``pg`` / ``postgres`` / ``postgresql`` — expects ``postgresql://``,
      ``postgresql+asyncpg://``, or ``postgres://``

    Args:
        backend: The database backend name.
        connection_string: The connection URI to validate.

    Returns:
        ``True`` if the connection string starts with an expected prefix
        for the given backend, ``False`` otherwise (including for unknown
        backends).
    """
    if not backend or not connection_string:
        return False

    normalised = backend.strip().lower()
    prefixes = _BACKEND_PREFIXES.get(normalised)

    if prefixes is None:
        return False

    conn_lower = connection_string.strip().lower()
    return any(conn_lower.startswith(prefix) for prefix in prefixes)


# ---------------------------------------------------------------------------
# Metadata filter parsing
# ---------------------------------------------------------------------------


def _resolve_dotted_key(data: dict[str, Any], dotted_key: str) -> tuple[bool, Any]:
    """Resolve a dot-notation key against a nested dictionary.

    Args:
        data: The dictionary to traverse.
        dotted_key: A key that may contain dots to indicate nesting
            (e.g. ``'team.name'``).

    Returns:
        A ``(found, value)`` tuple.  *found* is ``False`` when the key
        path does not exist in *data*.
    """
    parts = dotted_key.split(".")
    current: Any = data
    for part in parts:
        if not isinstance(current, dict) or part not in current:
            return False, None
        current = current[part]
    return True, current


def parse_metadata_filter(metadata_filter: dict[str, Any], metadata: dict[str, Any]) -> bool:
    """Check if all key-value pairs in *metadata_filter* exist in *metadata*.

    Keys in *metadata_filter* support **dot notation** to reach into nested
    dictionaries.  For example, the filter ``{"team.name": "backend"}``
    matches metadata ``{"team": {"name": "backend"}}``.

    Args:
        metadata_filter: The filter criteria — a flat dict whose keys may
            use dot notation for nested lookups.
        metadata: The metadata dict to match against.

    Returns:
        ``True`` if every key-value pair in *metadata_filter* is found
        (and equal) in *metadata*.

    Examples:
        >>> parse_metadata_filter({"env": "prod"}, {"env": "prod", "version": 2})
        True
        >>> parse_metadata_filter({"team.name": "api"}, {"team": {"name": "api"}})
        True
        >>> parse_metadata_filter({"env": "prod"}, {"env": "staging"})
        False
    """
    if not metadata_filter:
        return True

    for key, expected_value in metadata_filter.items():
        found, actual_value = _resolve_dotted_key(metadata, key)
        if not found or actual_value != expected_value:
            return False

    return True


# ---------------------------------------------------------------------------
# Timedelta formatting
# ---------------------------------------------------------------------------


def format_timedelta(td: timedelta) -> str:
    """Format a :class:`~datetime.timedelta` as a human-readable string.

    The output uses the largest applicable units from days, hours, and
    minutes (e.g. ``'2h 30m'``, ``'5d 12h'``, ``'45m'``).

    Negative timedeltas are prefixed with ``'-'``.

    Args:
        td: The timedelta to format.

    Returns:
        A compact human-readable duration string.  Returns ``'0m'`` for
        a zero-length timedelta.

    Examples:
        >>> from datetime import timedelta
        >>> format_timedelta(timedelta(hours=2, minutes=30))
        '2h 30m'
        >>> format_timedelta(timedelta(days=5, hours=12))
        '5d 12h'
        >>> format_timedelta(timedelta(seconds=90))
        '1m'
        >>> format_timedelta(timedelta(0))
        '0m'
    """
    total_seconds = int(td.total_seconds())

    negative = total_seconds < 0
    total_seconds = abs(total_seconds)

    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60

    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")

    if not parts:
        return "0m"

    result = " ".join(parts)
    return f"-{result}" if negative else result


# ---------------------------------------------------------------------------
# List chunking
# ---------------------------------------------------------------------------


def chunks(lst: list[Any], n: int) -> Iterator[list[Any]]:
    """Yield successive *n*-sized chunks from *lst*.

    The last chunk may contain fewer than *n* elements if the list length
    is not evenly divisible.

    Args:
        lst: The list to split.
        n: Maximum chunk size.  Must be at least ``1``.

    Yields:
        Sub-lists of at most *n* elements.

    Raises:
        ValueError: If *n* is less than ``1``.

    Examples:
        >>> list(chunks([1, 2, 3, 4, 5], 2))
        [[1, 2], [3, 4], [5]]
    """
    if n < 1:
        raise ValueError(f"Chunk size must be >= 1, got {n}")

    for i in range(0, len(lst), n):
        yield lst[i : i + n]


# ---------------------------------------------------------------------------
# Provider name sanitization
# ---------------------------------------------------------------------------

_SANITIZE_PATTERN = re.compile(r"[\s\-]+")


def sanitize_provider_name(name: str) -> str:
    """Normalize a provider name to a canonical form.

    The name is lowercased, stripped of leading/trailing whitespace, and
    any internal spaces or hyphens are replaced with underscores.

    Args:
        name: The raw provider name.

    Returns:
        The sanitized provider name.

    Examples:
        >>> sanitize_provider_name("  Open AI  ")
        'open_ai'
        >>> sanitize_provider_name("azure-openai")
        'azure_openai'
    """
    return _SANITIZE_PATTERN.sub("_", name.strip().lower())
