"""Key rotation strategies for selecting API keys."""

from __future__ import annotations

import random
from collections import defaultdict
from typing import Optional

from .enums import Provider, RotationStrategy, KeyStatus
from .exceptions import NoAvailableKeyError
from .models import APIKey


class KeyRotator:
    """Manages key selection using configurable rotation strategies.

    Supports round-robin, least-used, random, and weighted strategies.
    All strategies automatically skip keys that are inactive, rate-limited,
    expired, or at max concurrent usage.
    """

    def __init__(self, strategy: RotationStrategy | str = RotationStrategy.ROUND_ROBIN) -> None:
        """Initialize the rotator.

        Args:
            strategy: The rotation strategy to use.
        """
        if isinstance(strategy, str):
            strategy = RotationStrategy(strategy)
        self._strategy = strategy
        # Round-robin index per provider
        self._rr_counters: dict[str, int] = defaultdict(int)

    @property
    def strategy(self) -> RotationStrategy:
        """The current rotation strategy."""
        return self._strategy

    @strategy.setter
    def strategy(self, value: RotationStrategy | str) -> None:
        """Set the rotation strategy."""
        if isinstance(value, str):
            value = RotationStrategy(value)
        self._strategy = value

    def select_key(
        self,
        keys: list[APIKey],
        provider: Optional[Provider | str] = None,
    ) -> APIKey:
        """Select the next key using the configured strategy.

        Args:
            keys: List of candidate keys to choose from.
            provider: Optional provider to filter keys by.

        Returns:
            The selected APIKey.

        Raises:
            NoAvailableKeyError: If no suitable key is available.
        """
        # Filter to available keys
        available = self._filter_available(keys, provider)

        if not available:
            provider_name = (
                provider.value if isinstance(provider, Provider) else provider or "any"
            )
            raise NoAvailableKeyError(provider=provider_name)

        # Sort by priority (lower = higher priority)
        available.sort(key=lambda k: k.priority)

        # Apply strategy
        if self._strategy == RotationStrategy.ROUND_ROBIN:
            return self._round_robin(available, provider)
        elif self._strategy == RotationStrategy.LEAST_USED:
            return self._least_used(available)
        elif self._strategy == RotationStrategy.RANDOM:
            return self._random(available)
        elif self._strategy == RotationStrategy.WEIGHTED:
            return self._weighted(available)
        else:
            return self._round_robin(available, provider)

    def _filter_available(
        self,
        keys: list[APIKey],
        provider: Optional[Provider | str] = None,
    ) -> list[APIKey]:
        """Filter keys to only those that are available for use.

        A key is available if:
        - Status is ACTIVE
        - Not expired
        - Not rate-limited (daily and monthly counts under limits)
        - Concurrent usage under max_concurrent (if set)
        """
        available = []
        for key in keys:
            # Filter by provider if specified
            if provider is not None:
                provider_str = (
                    provider.value if isinstance(provider, Provider) else provider
                )
                key_provider_str = (
                    key.provider.value if isinstance(key.provider, Provider) else key.provider
                )
                if key_provider_str != provider_str:
                    continue

            # Check status
            key_status = key.status.value if isinstance(key.status, KeyStatus) else key.status
            if key_status != KeyStatus.ACTIVE.value:
                continue

            # Check capacity using model property
            if hasattr(key, "has_capacity") and not key.has_capacity:
                continue

            available.append(key)

        return available

    def _round_robin(
        self,
        keys: list[APIKey],
        provider: Optional[Provider | str] = None,
    ) -> APIKey:
        """Select key using round-robin within the provider group."""
        provider_key = str(provider) if provider else "_all"
        idx = self._rr_counters[provider_key] % len(keys)
        self._rr_counters[provider_key] = idx + 1
        return keys[idx]

    def _least_used(self, keys: list[APIKey]) -> APIKey:
        """Select the key with the lowest total usage count."""
        return min(keys, key=lambda k: k.total_usage_count)

    def _random(self, keys: list[APIKey]) -> APIKey:
        """Select a random key."""
        return random.choice(keys)

    def _weighted(self, keys: list[APIKey]) -> APIKey:
        """Select a key using weighted random selection.

        Keys with higher weight values are more likely to be selected.
        """
        weights = [k.weight for k in keys]
        return random.choices(keys, weights=weights, k=1)[0]

    def reset_counters(self, provider: Optional[str] = None) -> None:
        """Reset round-robin counters.

        Args:
            provider: If set, only reset the counter for this provider.
                     If None, reset all counters.
        """
        if provider:
            self._rr_counters.pop(provider, None)
        else:
            self._rr_counters.clear()
