"""Abstract base class for storage backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Optional

from ..enums import Provider, KeyStatus
from ..models import APIKey, KeyFilter, KeyUpdateRequest, BulkOperationResult


class StorageBackend(ABC):
    """Abstract base class defining the storage interface.

    All storage backends (Memory, SQLite, MongoDB, PostgreSQL) must implement
    this interface. Methods are async to support async database drivers.
    """

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the storage backend (create tables/collections).

        Must be called before any other operations.
        """
        ...

    @abstractmethod
    async def close(self) -> None:
        """Close connections and clean up resources."""
        ...

    # ── CRUD ───────────────────────────────────────────────────────────────

    @abstractmethod
    async def add_key(self, key: APIKey) -> APIKey:
        """Insert a new API key record.

        Args:
            key: The APIKey model to insert.

        Returns:
            The inserted APIKey (with generated ID if not set).

        Raises:
            DuplicateKeyError: If key_value + provider already exists.
        """
        ...

    @abstractmethod
    async def get_key(self, key_id: str) -> APIKey:
        """Retrieve a single key by its ID.

        Args:
            key_id: The unique key identifier.

        Returns:
            The matching APIKey.

        Raises:
            KeyNotFoundError: If no key exists with the given ID.
        """
        ...

    @abstractmethod
    async def get_keys_by_provider(self, provider: Provider) -> list[APIKey]:
        """Retrieve all keys for a specific provider.

        Args:
            provider: The API provider to filter by.

        Returns:
            List of matching APIKey records (may be empty).
        """
        ...

    @abstractmethod
    async def get_all_keys(self, key_filter: Optional[KeyFilter] = None) -> list[APIKey]:
        """Retrieve all keys, optionally filtered.

        Args:
            key_filter: Optional filter criteria.

        Returns:
            List of matching APIKey records.
        """
        ...

    @abstractmethod
    async def update_key(self, key_id: str, updates: KeyUpdateRequest) -> APIKey:
        """Partially update an existing key.

        Args:
            key_id: The key to update.
            updates: Fields to update (only set fields are applied).

        Returns:
            The updated APIKey.

        Raises:
            KeyNotFoundError: If no key exists with the given ID.
        """
        ...

    @abstractmethod
    async def delete_key(self, key_id: str, soft: bool = True) -> bool:
        """Delete a key.

        Args:
            key_id: The key to delete.
            soft: If True, mark as REVOKED instead of hard deleting.

        Returns:
            True if the key was found and deleted/revoked.

        Raises:
            KeyNotFoundError: If no key exists with the given ID.
        """
        ...

    # ── Usage Tracking ─────────────────────────────────────────────────────

    @abstractmethod
    async def increment_usage(
        self,
        key_id: str,
        daily: int = 1,
        monthly: int = 1,
        total: int = 1,
    ) -> None:
        """Atomically increment usage counters for a key.

        Args:
            key_id: The key whose counters to increment.
            daily: Amount to add to daily_usage_count.
            monthly: Amount to add to monthly_usage_count.
            total: Amount to add to total_usage_count.
        """
        ...

    @abstractmethod
    async def update_concurrent_usage(self, key_id: str, delta: int) -> int:
        """Atomically adjust the concurrent usage counter.

        Args:
            key_id: The key to update.
            delta: The change (+1 for acquire, -1 for release).

        Returns:
            The new concurrent_usage value after the update.

        Raises:
            KeyNotFoundError: If no key exists with the given ID.
        """
        ...

    @abstractmethod
    async def reset_daily_counts(self, before_date: date) -> int:
        """Reset daily_usage_count for all keys with last_reset_daily before the given date.

        Args:
            before_date: Reset keys whose last_reset_daily is before this date.

        Returns:
            Number of keys reset.
        """
        ...

    @abstractmethod
    async def reset_monthly_counts(self, before_date: date) -> int:
        """Reset monthly_usage_count for all keys with last_reset_monthly before the given date.

        Args:
            before_date: Reset keys whose last_reset_monthly is before this date.

        Returns:
            Number of keys reset.
        """
        ...

    @abstractmethod
    async def update_last_used(self, key_id: str) -> None:
        """Update the last_used_at timestamp for a key.

        Args:
            key_id: The key to update.
        """
        ...

    # ── Bulk Operations ────────────────────────────────────────────────────

    @abstractmethod
    async def bulk_add_keys(self, keys: list[APIKey]) -> BulkOperationResult:
        """Insert multiple keys at once.

        Args:
            keys: List of APIKey models to insert.

        Returns:
            BulkOperationResult with success/failure counts.
        """
        ...

    @abstractmethod
    async def bulk_delete_keys(self, key_ids: list[str], soft: bool = True) -> BulkOperationResult:
        """Delete multiple keys at once.

        Args:
            key_ids: List of key IDs to delete.
            soft: If True, mark as REVOKED instead of hard deleting.

        Returns:
            BulkOperationResult with success/failure counts.
        """
        ...

    # ── Health ─────────────────────────────────────────────────────────────

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the storage backend is healthy and reachable.

        Returns:
            True if the backend is operational.
        """
        ...

    @abstractmethod
    async def count_keys(
        self,
        provider: Optional[Provider] = None,
        status: Optional[KeyStatus] = None,
    ) -> int:
        """Count keys matching the given criteria.

        Args:
            provider: Optional provider filter.
            status: Optional status filter.

        Returns:
            Number of matching keys.
        """
        ...
