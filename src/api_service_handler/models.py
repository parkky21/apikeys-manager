from __future__ import annotations

"""Data models for API key management.

Provides Pydantic v2 models for API key storage, creation, update,
filtering, usage statistics, and bulk operation results.
"""

from datetime import date, datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from .enums import Environment, KeyStatus, Provider, RotationStrategy


# ---------------------------------------------------------------------------
# Main model
# ---------------------------------------------------------------------------


class APIKey(BaseModel):
    """Represents a single managed API key with usage tracking and metadata.

    Attributes:
        id: Unique identifier (UUID) for this key entry.
        provider: The service provider this key belongs to.
        key_value: The actual API key string (may be encrypted at rest).
        alias: Optional human-friendly name, e.g. ``'prod-openai-1'``.
        status: Current lifecycle status of the key.
        environment: Deployment environment the key is designated for.
        daily_limit: Maximum allowed requests per day (``None`` = unlimited).
        monthly_limit: Maximum allowed requests per month (``None`` = unlimited).
        daily_usage_count: Number of requests made today.
        monthly_usage_count: Number of requests made this month.
        total_usage_count: Lifetime request count.
        concurrent_usage: Number of in-flight requests right now.
        max_concurrent: Maximum simultaneous in-flight requests (``None`` = unlimited).
        weight: Relative weight for weighted-rotation strategies.
        priority: Priority rank — lower values are selected first.
        metadata: Arbitrary key/value pairs for user-defined data.
        tags: Free-form labels for categorisation and filtering.
        last_used_at: Timestamp of the most recent usage.
        last_reset_daily: Date when daily counters were last zeroed.
        last_reset_monthly: Date when monthly counters were last zeroed.
        expires_at: Optional expiration timestamp.
        created_at: Timestamp when this record was created.
        updated_at: Timestamp when this record was last modified.
    """

    model_config = ConfigDict(use_enum_values=True)

    id: str = Field(default_factory=lambda: str(uuid4()))
    provider: Provider
    key_value: str
    alias: Optional[str] = None
    status: KeyStatus = KeyStatus.ACTIVE
    environment: Environment = Environment.PRODUCTION

    # Rate limits
    daily_limit: Optional[int] = None
    monthly_limit: Optional[int] = None

    # Usage counters
    daily_usage_count: int = 0
    monthly_usage_count: int = 0
    total_usage_count: int = 0

    # Concurrent usage
    concurrent_usage: int = 0
    max_concurrent: Optional[int] = None

    # Rotation
    weight: int = 1
    priority: int = 0

    # Metadata
    metadata: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)

    # Timestamps
    last_used_at: Optional[datetime] = None
    last_reset_daily: date = Field(default_factory=date.today)
    last_reset_monthly: date = Field(default_factory=date.today)
    expires_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # -- Computed properties ------------------------------------------------

    @property
    def is_expired(self) -> bool:
        """Return ``True`` if the key has passed its expiration time."""
        if self.expires_at is None:
            return False
        now = datetime.now(timezone.utc)
        # Handle naive datetimes stored without tz info
        expires = self.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return now >= expires

    @property
    def is_rate_limited(self) -> bool:
        """Return ``True`` if any configured rate limit has been reached."""
        if self.daily_limit is not None and self.daily_usage_count >= self.daily_limit:
            return True
        if self.monthly_limit is not None and self.monthly_usage_count >= self.monthly_limit:
            return True
        return False

    @property
    def has_capacity(self) -> bool:
        """Return ``True`` if the key can accept another request right now.

        A key has capacity when it is **active**, **not expired**,
        **not rate-limited**, and below its concurrent-usage ceiling.
        """
        if self.is_expired:
            return False
        if self.is_rate_limited:
            return False
        if self.status != KeyStatus.ACTIVE:
            return False
        if self.max_concurrent is not None and self.concurrent_usage >= self.max_concurrent:
            return False
        return True

    @property
    def needs_daily_reset(self) -> bool:
        """Return ``True`` if daily counters are stale (belong to a previous day)."""
        return self.last_reset_daily < date.today()

    @property
    def needs_monthly_reset(self) -> bool:
        """Return ``True`` if monthly counters are stale (belong to a previous month)."""
        today = date.today()
        return (
            self.last_reset_monthly.year < today.year
            or self.last_reset_monthly.month < today.month
        )


# ---------------------------------------------------------------------------
# Request / response helpers
# ---------------------------------------------------------------------------


class KeyCreateRequest(BaseModel):
    """Input schema for creating a new API key.

    Only ``provider`` and ``key_value`` are mandatory; all other fields
    fall back to sensible defaults on the resulting :class:`APIKey`.
    """

    model_config = ConfigDict(use_enum_values=True)

    provider: Provider
    key_value: str
    alias: Optional[str] = None
    daily_limit: Optional[int] = None
    monthly_limit: Optional[int] = None
    max_concurrent: Optional[int] = None
    environment: Environment = Environment.PRODUCTION
    metadata: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    expires_at: Optional[datetime] = None
    weight: int = 1
    priority: int = 0


class KeyUpdateRequest(BaseModel):
    """Input schema for partially updating an existing API key.

    Every field is optional — only the fields that are set (not ``None``)
    should be applied to the target :class:`APIKey`.
    """

    model_config = ConfigDict(use_enum_values=True)

    alias: Optional[str] = None
    status: Optional[KeyStatus] = None
    daily_limit: Optional[int] = None
    monthly_limit: Optional[int] = None
    max_concurrent: Optional[int] = None
    environment: Optional[Environment] = None
    metadata: Optional[dict[str, Any]] = None
    tags: Optional[list[str]] = None
    expires_at: Optional[datetime] = None
    weight: Optional[int] = None
    priority: Optional[int] = None


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


class KeyFilter(BaseModel):
    """Declarative filter for querying stored API keys.

    Only non-``None`` fields participate in matching.  Use the
    :meth:`matches` helper to test a candidate :class:`APIKey`.
    """

    model_config = ConfigDict(use_enum_values=True)

    provider: Optional[Provider] = None
    status: Optional[KeyStatus] = None
    environment: Optional[Environment] = None
    tags: Optional[list[str]] = None
    metadata_filter: Optional[dict[str, Any]] = None
    has_capacity: Optional[bool] = None
    alias_contains: Optional[str] = None

    def matches(self, key: APIKey) -> bool:
        """Return ``True`` if *key* satisfies every set filter criterion.

        Args:
            key: The API key to evaluate.

        Returns:
            ``True`` when all non-``None`` filter fields match the key.
        """
        if self.provider is not None and key.provider != self.provider:
            return False
        if self.status is not None and key.status != self.status:
            return False
        if self.environment is not None and key.environment != self.environment:
            return False

        # Tag filter: at least one of the requested tags must be present
        if self.tags is not None:
            if not any(tag in key.tags for tag in self.tags):
                return False

        # Metadata filter: all key/value pairs must match
        if self.metadata_filter is not None:
            for meta_key, meta_value in self.metadata_filter.items():
                if key.metadata.get(meta_key) != meta_value:
                    return False

        # Capacity filter
        if self.has_capacity is not None:
            if key.has_capacity != self.has_capacity:
                return False

        # Alias substring search (case-insensitive)
        if self.alias_contains is not None:
            if key.alias is None:
                return False
            if self.alias_contains.lower() not in key.alias.lower():
                return False

        return True


# ---------------------------------------------------------------------------
# Usage statistics
# ---------------------------------------------------------------------------


class UsageStats(BaseModel):
    """Aggregated usage statistics snapshot for a single API key."""

    model_config = ConfigDict(use_enum_values=True)

    key_id: str
    provider: Provider
    alias: Optional[str] = None

    daily_usage_count: int = 0
    monthly_usage_count: int = 0
    total_usage_count: int = 0
    concurrent_usage: int = 0

    daily_limit: Optional[int] = None
    monthly_limit: Optional[int] = None
    max_concurrent: Optional[int] = None

    daily_remaining: Optional[int] = None
    monthly_remaining: Optional[int] = None

    last_used_at: Optional[datetime] = None
    status: KeyStatus = KeyStatus.ACTIVE


# ---------------------------------------------------------------------------
# Bulk operations
# ---------------------------------------------------------------------------


class BulkOperationResult(BaseModel):
    """Summary returned after a bulk create / update / delete operation."""

    total: int = 0
    successful: int = 0
    failed: int = 0
    errors: list[str] = Field(default_factory=list)
    created_ids: list[str] = Field(default_factory=list)
