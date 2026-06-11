"""In-memory storage backend for testing and lightweight use."""

from __future__ import annotations

import copy
from datetime import date, datetime, timezone
from typing import Optional

from ..enums import Provider, KeyStatus
from ..exceptions import KeyNotFoundError, DuplicateKeyError
from ..models import APIKey, KeyFilter, KeyUpdateRequest, BulkOperationResult
from .base import StorageBackend


class MemoryStorageBackend(StorageBackend):
    """In-memory dict-based storage backend.

    Suitable for testing, prototyping, and lightweight single-process use.
    Data is lost when the process exits.
    """

    def __init__(self) -> None:
        self._keys: dict[str, APIKey] = {}
        self._initialized: bool = False

    async def initialize(self) -> None:
        """Initialize the in-memory store."""
        self._keys = {}
        self._initialized = True

    async def close(self) -> None:
        """Clear the in-memory store."""
        self._keys.clear()
        self._initialized = False

    # ── CRUD ───────────────────────────────────────────────────────────────

    async def add_key(self, key: APIKey) -> APIKey:
        """Insert a new API key into memory."""
        # Check for duplicates (same key_value + provider)
        for existing in self._keys.values():
            if (
                existing.key_value == key.key_value
                and existing.provider == key.provider
                and existing.status != KeyStatus.REVOKED
            ):
                raise DuplicateKeyError(provider=str(key.provider), key_value=key.key_value)

        self._keys[key.id] = copy.deepcopy(key)
        return copy.deepcopy(key)

    async def get_key(self, key_id: str) -> APIKey:
        """Retrieve a key by ID."""
        if key_id not in self._keys:
            raise KeyNotFoundError(key_id=key_id)
        return copy.deepcopy(self._keys[key_id])

    async def get_keys_by_provider(self, provider: Provider) -> list[APIKey]:
        """Get all keys for a provider."""
        provider_str = provider.value if isinstance(provider, Provider) else provider
        return [
            copy.deepcopy(k)
            for k in self._keys.values()
            if (k.provider.value if isinstance(k.provider, Provider) else k.provider) == provider_str
        ]

    async def get_all_keys(self, key_filter: Optional[KeyFilter] = None) -> list[APIKey]:
        """Get all keys, optionally filtered."""
        keys = list(self._keys.values())
        if key_filter:
            keys = [k for k in keys if key_filter.matches(k)]
        return [copy.deepcopy(k) for k in keys]

    async def update_key(self, key_id: str, updates: KeyUpdateRequest) -> APIKey:
        """Update a key's fields."""
        if key_id not in self._keys:
            raise KeyNotFoundError(key_id=key_id)

        key = self._keys[key_id]
        update_data = updates.model_dump(exclude_unset=True)

        for field_name, value in update_data.items():
            setattr(key, field_name, value)

        key.updated_at = datetime.now(timezone.utc)
        self._keys[key_id] = key
        return copy.deepcopy(key)

    async def delete_key(self, key_id: str, soft: bool = True) -> bool:
        """Delete or revoke a key."""
        if key_id not in self._keys:
            raise KeyNotFoundError(key_id=key_id)

        if soft:
            self._keys[key_id].status = KeyStatus.REVOKED
            self._keys[key_id].updated_at = datetime.now(timezone.utc)
        else:
            del self._keys[key_id]

        return True

    # ── Usage Tracking ─────────────────────────────────────────────────────

    async def increment_usage(
        self,
        key_id: str,
        daily: int = 1,
        monthly: int = 1,
        total: int = 1,
    ) -> None:
        """Increment usage counters."""
        if key_id not in self._keys:
            raise KeyNotFoundError(key_id=key_id)

        key = self._keys[key_id]
        key.daily_usage_count += daily
        key.monthly_usage_count += monthly
        key.total_usage_count += total
        key.last_used_at = datetime.now(timezone.utc)
        key.updated_at = datetime.now(timezone.utc)

    async def update_concurrent_usage(self, key_id: str, delta: int) -> int:
        """Adjust concurrent usage counter."""
        if key_id not in self._keys:
            raise KeyNotFoundError(key_id=key_id)

        key = self._keys[key_id]
        key.concurrent_usage = max(0, key.concurrent_usage + delta)
        key.updated_at = datetime.now(timezone.utc)
        return key.concurrent_usage

    async def reset_daily_counts(self, before_date: date) -> int:
        """Reset daily counts for keys not yet reset today."""
        count = 0
        for key in self._keys.values():
            if key.last_reset_daily < before_date:
                key.daily_usage_count = 0
                key.last_reset_daily = before_date
                if key.status == KeyStatus.RATE_LIMITED:
                    # Check if monthly limit is also hit
                    if key.monthly_limit is None or key.monthly_usage_count < key.monthly_limit:
                        key.status = KeyStatus.ACTIVE
                key.updated_at = datetime.now(timezone.utc)
                count += 1
        return count

    async def reset_monthly_counts(self, before_date: date) -> int:
        """Reset monthly counts for keys not yet reset this month."""
        count = 0
        for key in self._keys.values():
            if (
                key.last_reset_monthly.month != before_date.month
                or key.last_reset_monthly.year != before_date.year
            ):
                key.monthly_usage_count = 0
                key.last_reset_monthly = before_date
                if key.status == KeyStatus.RATE_LIMITED:
                    key.status = KeyStatus.ACTIVE
                key.updated_at = datetime.now(timezone.utc)
                count += 1
        return count

    async def update_last_used(self, key_id: str) -> None:
        """Update last_used_at timestamp."""
        if key_id not in self._keys:
            raise KeyNotFoundError(key_id=key_id)
        self._keys[key_id].last_used_at = datetime.now(timezone.utc)

    # ── Bulk Operations ────────────────────────────────────────────────────

    async def bulk_add_keys(self, keys: list[APIKey]) -> BulkOperationResult:
        """Insert multiple keys."""
        result = BulkOperationResult(total=len(keys))

        for key in keys:
            try:
                added = await self.add_key(key)
                result.successful += 1
                result.created_ids.append(added.id)
            except Exception as e:
                result.failed += 1
                result.errors.append(f"Key {key.alias or key.id}: {e}")

        return result

    async def bulk_delete_keys(self, key_ids: list[str], soft: bool = True) -> BulkOperationResult:
        """Delete multiple keys."""
        result = BulkOperationResult(total=len(key_ids))

        for key_id in key_ids:
            try:
                await self.delete_key(key_id, soft=soft)
                result.successful += 1
            except Exception as e:
                result.failed += 1
                result.errors.append(f"Key {key_id}: {e}")

        return result

    # ── Health ─────────────────────────────────────────────────────────────

    async def health_check(self) -> bool:
        """Memory backend is always healthy if initialized."""
        return self._initialized

    async def count_keys(
        self,
        provider: Optional[Provider] = None,
        status: Optional[KeyStatus] = None,
    ) -> int:
        """Count keys matching criteria."""
        count = 0
        for key in self._keys.values():
            if provider is not None:
                provider_str = provider.value if isinstance(provider, Provider) else provider
                key_provider_str = (
                    key.provider.value if isinstance(key.provider, Provider) else key.provider
                )
                if key_provider_str != provider_str:
                    continue
            if status is not None:
                status_str = status.value if isinstance(status, KeyStatus) else status
                key_status_str = (
                    key.status.value if isinstance(key.status, KeyStatus) else key.status
                )
                if key_status_str != status_str:
                    continue
            count += 1
        return count
