"""Rate limiting enforcement for API keys."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from .enums import KeyStatus
from .exceptions import RateLimitExceededError
from .models import APIKey
from .storage.base import StorageBackend


class RateLimiter:
    """Enforces daily and monthly rate limits on API keys.

    Handles:
    - Checking if a key has capacity before use
    - Auto-resetting daily/monthly counters when the period rolls over
    - Marking keys as RATE_LIMITED when limits are hit
    - Recovering keys when counters reset
    """

    def __init__(self, storage: StorageBackend, auto_reset: bool = True) -> None:
        """Initialize the rate limiter.

        Args:
            storage: The storage backend for persisting counter changes.
            auto_reset: If True, auto-reset expired counters on access.
        """
        self._storage = storage
        self._auto_reset = auto_reset

    async def check_and_update(self, key: APIKey) -> APIKey:
        """Check if a key needs counter resets and apply them.

        This is called before using a key to ensure counters are current.

        Args:
            key: The API key to check.

        Returns:
            The updated key (with reset counters if applicable).
        """
        if not self._auto_reset:
            return key

        today = date.today()
        needs_refresh = False

        # Check daily reset
        if key.needs_daily_reset:
            await self._storage.reset_daily_counts(today)
            needs_refresh = True

        # Check monthly reset
        if key.needs_monthly_reset:
            await self._storage.reset_monthly_counts(today)
            needs_refresh = True

        if needs_refresh:
            key = await self._storage.get_key(key.id)

        return key

    async def check_capacity(self, key: APIKey) -> bool:
        """Check if a key has remaining capacity.

        Args:
            key: The key to check.

        Returns:
            True if the key can accept more requests.
        """
        key = await self.check_and_update(key)

        # Check daily limit
        if key.daily_limit is not None and key.daily_usage_count >= key.daily_limit:
            return False

        # Check monthly limit
        if key.monthly_limit is not None and key.monthly_usage_count >= key.monthly_limit:
            return False

        # Check concurrent limit
        if key.max_concurrent is not None and key.concurrent_usage >= key.max_concurrent:
            return False

        return True

    async def enforce_limits(self, key: APIKey) -> APIKey:
        """Enforce rate limits, raising an exception if limits are exceeded.

        Call this before each API request to ensure the key is within limits.

        Args:
            key: The key to check.

        Returns:
            The validated key.

        Raises:
            RateLimitExceededError: If daily or monthly limit is exceeded.
        """
        key = await self.check_and_update(key)

        # Check daily limit
        if key.daily_limit is not None and key.daily_usage_count >= key.daily_limit:
            # Mark as rate limited
            from .models import KeyUpdateRequest
            await self._storage.update_key(
                key.id,
                KeyUpdateRequest(status=KeyStatus.RATE_LIMITED),
            )
            raise RateLimitExceededError(
                key_id=key.id,
                limit_type="daily",
                limit=key.daily_limit,
                current=key.daily_usage_count,
            )

        # Check monthly limit
        if key.monthly_limit is not None and key.monthly_usage_count >= key.monthly_limit:
            from .models import KeyUpdateRequest
            await self._storage.update_key(
                key.id,
                KeyUpdateRequest(status=KeyStatus.RATE_LIMITED),
            )
            raise RateLimitExceededError(
                key_id=key.id,
                limit_type="monthly",
                limit=key.monthly_limit,
                current=key.monthly_usage_count,
            )

        return key

    async def record_usage(self, key_id: str) -> None:
        """Record a single usage event for a key.

        Increments daily, monthly, and total counters by 1.

        Args:
            key_id: The key to record usage for.
        """
        await self._storage.increment_usage(key_id, daily=1, monthly=1, total=1)

    async def get_remaining(self, key: APIKey) -> dict[str, Optional[int]]:
        """Get remaining capacity for a key.

        Args:
            key: The key to check.

        Returns:
            Dict with 'daily_remaining', 'monthly_remaining' values.
            None means unlimited.
        """
        key = await self.check_and_update(key)

        daily_remaining = None
        if key.daily_limit is not None:
            daily_remaining = max(0, key.daily_limit - key.daily_usage_count)

        monthly_remaining = None
        if key.monthly_limit is not None:
            monthly_remaining = max(0, key.monthly_limit - key.monthly_usage_count)

        return {
            "daily_remaining": daily_remaining,
            "monthly_remaining": monthly_remaining,
        }

    async def reset_daily(self) -> int:
        """Manually trigger a daily reset for all keys.

        Returns:
            Number of keys reset.
        """
        return await self._storage.reset_daily_counts(date.today())

    async def reset_monthly(self) -> int:
        """Manually trigger a monthly reset for all keys.

        Returns:
            Number of keys reset.
        """
        return await self._storage.reset_monthly_counts(date.today())
