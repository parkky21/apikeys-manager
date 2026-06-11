"""Usage tracking and concurrent usage management."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator, Optional

from .enums import Provider, KeyStatus
from .exceptions import MaxConcurrentExceededError, KeyNotFoundError
from .models import APIKey, UsageStats
from .storage.base import StorageBackend


class UsageTracker:
    """Tracks API key usage including counts and concurrent usage.

    Provides:
    - Usage recording (daily, monthly, total increments)
    - Concurrent usage acquire/release with max enforcement
    - Context manager for safe concurrent usage
    - Usage statistics aggregation
    """

    def __init__(self, storage: StorageBackend) -> None:
        """Initialize the usage tracker.

        Args:
            storage: The storage backend for persisting usage data.
        """
        self._storage = storage

    async def record_usage(self, key_id: str, count: int = 1) -> None:
        """Record usage for a key.

        Increments daily, monthly, and total counters.

        Args:
            key_id: The key to record usage for.
            count: Number of uses to record (default: 1).
        """
        await self._storage.increment_usage(
            key_id, daily=count, monthly=count, total=count
        )

    async def acquire(self, key_id: str) -> int:
        """Acquire concurrent usage slot for a key.

        Increments the concurrent_usage counter by 1.
        Checks max_concurrent limit before acquiring.

        Args:
            key_id: The key to acquire a slot for.

        Returns:
            The new concurrent_usage value.

        Raises:
            MaxConcurrentExceededError: If max_concurrent would be exceeded.
            KeyNotFoundError: If the key doesn't exist.
        """
        # Check current state
        key = await self._storage.get_key(key_id)

        if (
            key.max_concurrent is not None
            and key.concurrent_usage >= key.max_concurrent
        ):
            raise MaxConcurrentExceededError(
                key_id=key_id,
                max_concurrent=key.max_concurrent,
            )

        return await self._storage.update_concurrent_usage(key_id, delta=1)

    async def release(self, key_id: str) -> int:
        """Release a concurrent usage slot for a key.

        Decrements the concurrent_usage counter by 1 (min 0).

        Args:
            key_id: The key to release a slot for.

        Returns:
            The new concurrent_usage value.
        """
        return await self._storage.update_concurrent_usage(key_id, delta=-1)

    @asynccontextmanager
    async def use(self, key_id: str, record: bool = True) -> AsyncIterator[APIKey]:
        """Context manager for using a key with automatic acquire/release.

        Acquires a concurrent slot on entry, releases on exit.
        Optionally records usage on successful exit.

        Args:
            key_id: The key to use.
            record: If True, record a usage event on successful exit.

        Yields:
            The APIKey being used.

        Example:
            async with tracker.use(key.id) as key:
                # concurrent_usage is incremented
                response = await call_api(key.key_value)
            # concurrent_usage is decremented, usage recorded
        """
        await self.acquire(key_id)
        try:
            key = await self._storage.get_key(key_id)
            yield key
            # Only record usage if the block completed successfully
            if record:
                await self.record_usage(key_id)
        finally:
            await self.release(key_id)

    async def get_concurrent_usage(self, key_id: str) -> int:
        """Get the current concurrent usage count for a key.

        Args:
            key_id: The key to check.

        Returns:
            Current concurrent_usage value.
        """
        key = await self._storage.get_key(key_id)
        return key.concurrent_usage

    async def get_usage_stats(self, key_id: str) -> UsageStats:
        """Get aggregated usage statistics for a key.

        Args:
            key_id: The key to get stats for.

        Returns:
            UsageStats with all usage information.
        """
        key = await self._storage.get_key(key_id)

        daily_remaining = None
        if key.daily_limit is not None:
            daily_remaining = max(0, key.daily_limit - key.daily_usage_count)

        monthly_remaining = None
        if key.monthly_limit is not None:
            monthly_remaining = max(0, key.monthly_limit - key.monthly_usage_count)

        return UsageStats(
            key_id=key.id,
            provider=key.provider,
            alias=key.alias,
            daily_usage_count=key.daily_usage_count,
            monthly_usage_count=key.monthly_usage_count,
            total_usage_count=key.total_usage_count,
            concurrent_usage=key.concurrent_usage,
            daily_limit=key.daily_limit,
            monthly_limit=key.monthly_limit,
            max_concurrent=key.max_concurrent,
            daily_remaining=daily_remaining,
            monthly_remaining=monthly_remaining,
            last_used_at=key.last_used_at,
            status=key.status,
        )

    async def get_provider_stats(self, provider: Provider | str) -> list[UsageStats]:
        """Get usage stats for all keys of a provider.

        Args:
            provider: The provider to get stats for.

        Returns:
            List of UsageStats for all keys of the provider.
        """
        if isinstance(provider, str):
            provider = Provider(provider)

        keys = await self._storage.get_keys_by_provider(provider)
        stats = []
        for key in keys:
            stats.append(await self.get_usage_stats(key.id))
        return stats

    async def reset_concurrent(self, key_id: str) -> None:
        """Reset concurrent usage to 0 for a key.

        Useful for recovery after crashes where release wasn't called.

        Args:
            key_id: The key to reset.
        """
        key = await self._storage.get_key(key_id)
        if key.concurrent_usage > 0:
            # Set to 0 by decrementing current value
            await self._storage.update_concurrent_usage(key_id, delta=-key.concurrent_usage)

    async def reset_all_concurrent(self) -> int:
        """Reset concurrent usage to 0 for all keys.

        Useful for application startup recovery.

        Returns:
            Number of keys reset.
        """
        from .models import KeyFilter
        all_keys = await self._storage.get_all_keys()
        count = 0
        for key in all_keys:
            if key.concurrent_usage > 0:
                await self._storage.update_concurrent_usage(
                    key.id, delta=-key.concurrent_usage
                )
                count += 1
        return count
