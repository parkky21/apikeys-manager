"""Main client for the API Service Handler library."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Optional

from .config import ASHConfig
from .encryption import decrypt_api_key, encrypt_api_key
from .enums import (
    Environment,
    KeyStatus,
    Provider,
    RotationStrategy,
    StorageBackend as StorageBackendEnum,
)
from .exceptions import (
    NoAvailableKeyError,
    StorageNotInitializedError,
)
from .models import (
    APIKey,
    BulkOperationResult,
    KeyCreateRequest,
    KeyFilter,
    KeyUpdateRequest,
    UsageStats,
)
from .rate_limiter import RateLimiter
from .rotation import KeyRotator
from .storage.base import StorageBackend
from .usage_tracker import UsageTracker


def _create_storage(config: ASHConfig) -> StorageBackend:
    """Create a storage backend from config.

    Args:
        config: The ASH configuration.

    Returns:
        An uninitialized storage backend instance.
    """
    backend = config.storage_backend.lower()

    if backend == "memory":
        from .storage.memory import MemoryStorageBackend
        return MemoryStorageBackend()

    elif backend == "sqlite":
        from .storage.sqlite import SQLiteStorageBackend
        return SQLiteStorageBackend(config.connection_string)

    elif backend == "mongodb":
        from .storage.mongodb import MongoDBStorageBackend
        return MongoDBStorageBackend(config.connection_string)

    elif backend == "postgresql":
        from .storage.postgresql import PostgreSQLStorageBackend
        return PostgreSQLStorageBackend(config.connection_string)

    else:
        raise ValueError(
            f"Unknown storage backend: '{backend}'. "
            f"Supported: memory, sqlite, mongodb, postgresql"
        )


class APIServiceHandler:
    """Main entry point for the API Service Handler library.

    Provides a unified async API for managing API keys across providers
    with support for:
    - CRUD operations on API keys
    - Multiple storage backends (memory, SQLite, MongoDB, PostgreSQL)
    - AES-256-GCM encryption of key values at rest
    - Round-robin, least-used, random, and weighted key rotation
    - Daily and monthly rate limiting with auto-reset
    - Concurrent usage tracking with acquire/release
    - Metadata and tag-based filtering
    - Bulk operations

    Example::

        handler = APIServiceHandler(
            storage_backend="sqlite",
            connection_string="sqlite:///keys.db",
            shared_secret="my-secret",
        )
        await handler.initialize()

        key = await handler.add_key(
            provider=Provider.OPENAI,
            key_value="sk-abc123...",
            alias="prod-openai-1",
            daily_limit=1000,
        )

        async with handler.use_key(Provider.OPENAI) as active_key:
            response = await call_api(active_key.key_value)

        await handler.close()
    """

    def __init__(
        self,
        storage_backend: str = "memory",
        connection_string: str = "",
        shared_secret: str = "",
        rotation_strategy: str = "round_robin",
        encrypt_keys: bool = True,
        auto_reset_counters: bool = True,
        soft_delete: bool = True,
        default_daily_limit: Optional[int] = None,
        default_monthly_limit: Optional[int] = None,
        default_max_concurrent: Optional[int] = None,
        config: Optional[ASHConfig] = None,
    ) -> None:
        """Initialize the API Service Handler.

        Args:
            storage_backend: Storage backend name ('memory', 'sqlite', 'mongodb', 'postgresql').
            connection_string: Database connection string.
            shared_secret: Secret for AES-GCM encryption. Falls back to ASH_SHARED_SECRET env var.
            rotation_strategy: Key selection strategy ('round_robin', 'least_used', 'random', 'weighted').
            encrypt_keys: Whether to encrypt key values at rest.
            auto_reset_counters: Auto-reset daily/monthly counters when stale.
            soft_delete: Use soft delete (mark as REVOKED) instead of hard delete.
            default_daily_limit: Default daily limit for new keys.
            default_monthly_limit: Default monthly limit for new keys.
            default_max_concurrent: Default max concurrent for new keys.
            config: Optional pre-built ASHConfig (overrides individual params).
        """
        if config:
            self._config = config
        else:
            self._config = ASHConfig(
                storage_backend=storage_backend,
                connection_string=connection_string,
                shared_secret=shared_secret,
                encrypt_keys=encrypt_keys,
                rotation_strategy=rotation_strategy,
                auto_reset_counters=auto_reset_counters,
                soft_delete=soft_delete,
                default_daily_limit=default_daily_limit,
                default_monthly_limit=default_monthly_limit,
                default_max_concurrent=default_max_concurrent,
            )

        self._storage: StorageBackend = _create_storage(self._config)
        self._rotator = KeyRotator(self._config.rotation_strategy)
        self._rate_limiter: Optional[RateLimiter] = None
        self._usage_tracker: Optional[UsageTracker] = None
        self._initialized = False

    @property
    def config(self) -> ASHConfig:
        """The current configuration."""
        return self._config

    @property
    def storage(self) -> StorageBackend:
        """The underlying storage backend."""
        return self._storage

    @property
    def is_initialized(self) -> bool:
        """Whether the handler has been initialized."""
        return self._initialized

    # ── Lifecycle ──────────────────────────────────────────────────────────

    async def initialize(self) -> None:
        """Initialize the storage backend and internal components.

        Must be called before any other operations.
        """
        await self._storage.initialize()
        self._rate_limiter = RateLimiter(
            self._storage, auto_reset=self._config.auto_reset_counters
        )
        self._usage_tracker = UsageTracker(self._storage)
        self._initialized = True

    async def close(self) -> None:
        """Close the storage backend and clean up resources."""
        if self._storage:
            await self._storage.close()
        self._initialized = False

    def _ensure_initialized(self) -> None:
        """Raise if not initialized."""
        if not self._initialized:
            raise StorageNotInitializedError()

    # ── Key CRUD ──────────────────────────────────────────────────────────

    async def add_key(
        self,
        provider: Provider | str,
        key_value: str,
        alias: Optional[str] = None,
        daily_limit: Optional[int] = None,
        monthly_limit: Optional[int] = None,
        max_concurrent: Optional[int] = None,
        environment: Environment | str = Environment.PRODUCTION,
        metadata: Optional[dict[str, Any]] = None,
        tags: Optional[list[str]] = None,
        expires_at: Optional[datetime] = None,
        weight: int = 1,
        priority: int = 0,
    ) -> APIKey:
        """Add a new API key.

        Args:
            provider: The API provider (e.g., Provider.OPENAI or "openai").
            key_value: The actual API key string.
            alias: Human-friendly name for the key.
            daily_limit: Max requests per day (None = unlimited).
            monthly_limit: Max requests per month (None = unlimited).
            max_concurrent: Max simultaneous uses (None = unlimited).
            environment: Deployment environment.
            metadata: Arbitrary key-value metadata.
            tags: Free-form tags.
            expires_at: Expiration timestamp.
            weight: Weight for weighted rotation (default: 1).
            priority: Priority rank, lower = higher priority (default: 0).

        Returns:
            The created APIKey with generated ID.
        """
        self._ensure_initialized()

        # Resolve provider
        if isinstance(provider, str):
            provider = Provider.from_string(provider)

        # Apply defaults from config
        if daily_limit is None and self._config.default_daily_limit is not None:
            daily_limit = self._config.default_daily_limit
        if monthly_limit is None and self._config.default_monthly_limit is not None:
            monthly_limit = self._config.default_monthly_limit
        if max_concurrent is None and self._config.default_max_concurrent is not None:
            max_concurrent = self._config.default_max_concurrent

        # Encrypt key value if configured
        stored_key_value = key_value
        if self._config.encrypt_keys and self._config.shared_secret:
            stored_key_value = encrypt_api_key(key_value, self._config.shared_secret)

        key = APIKey(
            provider=provider,
            key_value=stored_key_value,
            alias=alias,
            daily_limit=daily_limit,
            monthly_limit=monthly_limit,
            max_concurrent=max_concurrent,
            environment=environment,
            metadata=metadata or {},
            tags=tags or [],
            expires_at=expires_at,
            weight=weight,
            priority=priority,
        )

        return await self._storage.add_key(key)

    async def get_key(self, key_id: str, decrypt: bool = True) -> APIKey:
        """Get a key by its ID.

        Args:
            key_id: The unique key identifier.
            decrypt: If True, decrypt the key_value before returning.

        Returns:
            The matching APIKey.
        """
        self._ensure_initialized()
        key = await self._storage.get_key(key_id)
        if decrypt and self._config.shared_secret:
            key.key_value = decrypt_api_key(key.key_value, self._config.shared_secret)
        return key

    async def get_keys_by_provider(
        self,
        provider: Provider | str,
        decrypt: bool = False,
    ) -> list[APIKey]:
        """Get all keys for a specific provider.

        Args:
            provider: The API provider to filter by.
            decrypt: If True, decrypt key values.

        Returns:
            List of matching APIKey records.
        """
        self._ensure_initialized()
        if isinstance(provider, str):
            provider = Provider.from_string(provider)
        keys = await self._storage.get_keys_by_provider(provider)
        if decrypt and self._config.shared_secret:
            for key in keys:
                key.key_value = decrypt_api_key(key.key_value, self._config.shared_secret)
        return keys

    async def get_all_keys(
        self,
        provider: Optional[Provider | str] = None,
        status: Optional[KeyStatus | str] = None,
        environment: Optional[Environment | str] = None,
        tags: Optional[list[str]] = None,
        metadata_filter: Optional[dict[str, Any]] = None,
        has_capacity: Optional[bool] = None,
        alias_contains: Optional[str] = None,
        decrypt: bool = False,
    ) -> list[APIKey]:
        """Get all keys with optional filtering.

        Args:
            provider: Filter by provider.
            status: Filter by status.
            environment: Filter by environment.
            tags: Filter by tags (any match).
            metadata_filter: Filter by metadata (all must match).
            has_capacity: If True, only keys with remaining capacity.
            alias_contains: Substring search on alias.
            decrypt: If True, decrypt key values.

        Returns:
            List of matching APIKey records.
        """
        self._ensure_initialized()

        # Build filter
        key_filter = None
        if any(
            v is not None
            for v in [provider, status, environment, tags, metadata_filter, has_capacity, alias_contains]
        ):
            # Resolve enums
            if isinstance(provider, str):
                provider = Provider.from_string(provider)
            if isinstance(status, str):
                status = KeyStatus(status)
            if isinstance(environment, str):
                environment = Environment(environment)

            key_filter = KeyFilter(
                provider=provider,
                status=status,
                environment=environment,
                tags=tags,
                metadata_filter=metadata_filter,
                has_capacity=has_capacity,
                alias_contains=alias_contains,
            )

        keys = await self._storage.get_all_keys(key_filter)
        if decrypt and self._config.shared_secret:
            for key in keys:
                key.key_value = decrypt_api_key(key.key_value, self._config.shared_secret)
        return keys

    async def update_key(
        self,
        key_id: str,
        alias: Optional[str] = None,
        status: Optional[KeyStatus | str] = None,
        daily_limit: Optional[int] = None,
        monthly_limit: Optional[int] = None,
        max_concurrent: Optional[int] = None,
        environment: Optional[Environment | str] = None,
        metadata: Optional[dict[str, Any]] = None,
        tags: Optional[list[str]] = None,
        expires_at: Optional[datetime] = None,
        weight: Optional[int] = None,
        priority: Optional[int] = None,
    ) -> APIKey:
        """Update an existing key's fields.

        Only provided (non-None) fields are updated.

        Args:
            key_id: The key to update.
            alias: New alias.
            status: New status.
            daily_limit: New daily limit.
            monthly_limit: New monthly limit.
            max_concurrent: New max concurrent.
            environment: New environment.
            metadata: New metadata (replaces existing).
            tags: New tags (replaces existing).
            expires_at: New expiration.
            weight: New weight.
            priority: New priority.

        Returns:
            The updated APIKey.
        """
        self._ensure_initialized()

        kwargs = {}
        if alias is not None: kwargs["alias"] = alias
        if status is not None: kwargs["status"] = KeyStatus(status) if isinstance(status, str) else status
        if daily_limit is not None: kwargs["daily_limit"] = daily_limit
        if monthly_limit is not None: kwargs["monthly_limit"] = monthly_limit
        if max_concurrent is not None: kwargs["max_concurrent"] = max_concurrent
        if environment is not None: kwargs["environment"] = Environment(environment) if isinstance(environment, str) else environment
        if metadata is not None: kwargs["metadata"] = metadata
        if tags is not None: kwargs["tags"] = tags
        if expires_at is not None: kwargs["expires_at"] = expires_at
        if weight is not None: kwargs["weight"] = weight
        if priority is not None: kwargs["priority"] = priority
            
        req = KeyUpdateRequest(**kwargs)

        return await self._storage.update_key(key_id, req)

    async def delete_key(self, key_id: str, hard: bool = False) -> bool:
        """Delete a key.

        Args:
            key_id: The key to delete.
            hard: If True, permanently delete. If False, soft delete (mark as REVOKED).

        Returns:
            True if the key was found and deleted.
        """
        self._ensure_initialized()
        soft = not hard and self._config.soft_delete
        return await self._storage.delete_key(key_id, soft=soft)

    # ── Key Selection ─────────────────────────────────────────────────────

    async def get_next_key(
        self,
        provider: Provider | str,
        environment: Optional[Environment | str] = None,
        tags: Optional[list[str]] = None,
        metadata_filter: Optional[dict[str, Any]] = None,
        alias_contains: Optional[str] = None,
        decrypt: bool = True,
    ) -> APIKey:
        """Get the next available key for a provider using the rotation strategy.

        Automatically handles:
        - Counter resets (daily/monthly)
        - Skipping rate-limited, expired, or inactive keys
        - Round-robin, least-used, random, or weighted selection
        - Filtering by environment, tags, metadata, and alias

        Args:
            provider: The API provider.
            environment: Optional environment filter.
            tags: Optional tags filter.
            metadata_filter: Optional metadata filter.
            alias_contains: Optional alias substring filter.
            decrypt: If True, decrypt the key value.

        Returns:
            The selected APIKey ready for use.

        Raises:
            NoAvailableKeyError: If no suitable key is available.
        """
        self._ensure_initialized()

        if isinstance(provider, str):
            provider = Provider.from_string(provider)

        # Get all keys for the provider matching filters
        keys = await self.get_all_keys(
            provider=provider,
            environment=environment,
            tags=tags,
            metadata_filter=metadata_filter,
            alias_contains=alias_contains,
        )

        # Auto-reset stale counters
        if self._rate_limiter:
            refreshed_keys = []
            for key in keys:
                key = await self._rate_limiter.check_and_update(key)
                refreshed_keys.append(key)
            keys = refreshed_keys

        # Use rotator to select the best key
        selected = self._rotator.select_key(keys, provider)

        if decrypt and self._config.shared_secret:
            selected.key_value = decrypt_api_key(
                selected.key_value, self._config.shared_secret
            )

        return selected

    @asynccontextmanager
    async def use_key(
        self,
        provider: Provider | str,
        environment: Optional[Environment | str] = None,
        tags: Optional[list[str]] = None,
        metadata_filter: Optional[dict[str, Any]] = None,
        alias_contains: Optional[str] = None,
        decrypt: bool = True,
    ) -> AsyncIterator[APIKey]:
        """Context manager for using a key with automatic lifecycle management.

        Selects the best available key, acquires a concurrent slot, yields the key,
        then releases the slot and records usage on successful completion.

        Args:
            provider: The API provider.
            environment: Optional environment filter.
            tags: Optional tags filter.
            metadata_filter: Optional metadata filter.
            alias_contains: Optional alias substring filter.
            decrypt: If True, decrypt the key value.

        Yields:
            The selected APIKey ready for use.

        Example::

            async with handler.use_key(Provider.OPENAI) as key:
                response = await call_openai_api(key.key_value)
            # concurrent_usage decremented, usage recorded
        """
        self._ensure_initialized()

        # Select the next key
        key = await self.get_next_key(
            provider=provider,
            environment=environment,
            tags=tags,
            metadata_filter=metadata_filter,
            alias_contains=alias_contains,
            decrypt=decrypt,
        )

        # Acquire concurrent slot and manage lifecycle
        assert self._usage_tracker is not None
        async with self._usage_tracker.use(key.id, record=True) as used_key:
            # Replace the key value with decrypted version if needed
            if decrypt and self._config.shared_secret:
                used_key.key_value = decrypt_api_key(
                    used_key.key_value, self._config.shared_secret
                )
            yield used_key

    # ── Usage & Stats ─────────────────────────────────────────────────────

    async def record_usage(self, key_id: str, count: int = 1) -> None:
        """Record usage for a specific key.

        Args:
            key_id: The key to record usage for.
            count: Number of uses to record.
        """
        self._ensure_initialized()
        assert self._usage_tracker is not None
        await self._usage_tracker.record_usage(key_id, count)

    async def get_usage_stats(self, key_id: str) -> UsageStats:
        """Get usage statistics for a key.

        Args:
            key_id: The key to get stats for.

        Returns:
            UsageStats with all usage information.
        """
        self._ensure_initialized()
        assert self._usage_tracker is not None
        return await self._usage_tracker.get_usage_stats(key_id)

    async def get_concurrent_usage(self, key_id: str) -> int:
        """Get current concurrent usage for a key.

        Args:
            key_id: The key to check.

        Returns:
            Current number of concurrent uses.
        """
        self._ensure_initialized()
        assert self._usage_tracker is not None
        return await self._usage_tracker.get_concurrent_usage(key_id)

    async def get_provider_stats(self, provider: Provider | str) -> list[UsageStats]:
        """Get usage stats for all keys of a provider.

        Args:
            provider: The provider to get stats for.

        Returns:
            List of UsageStats for all keys of the provider.
        """
        self._ensure_initialized()
        assert self._usage_tracker is not None
        return await self._usage_tracker.get_provider_stats(provider)

    # ── Bulk Operations ───────────────────────────────────────────────────

    async def bulk_add_keys(
        self,
        keys: list[dict[str, Any] | KeyCreateRequest],
    ) -> BulkOperationResult:
        """Add multiple keys at once.

        Args:
            keys: List of key data (dicts or KeyCreateRequest objects).

        Returns:
            BulkOperationResult with success/failure counts.
        """
        self._ensure_initialized()

        api_keys = []
        for key_data in keys:
            if isinstance(key_data, dict):
                key_data = KeyCreateRequest(**key_data)

            # Resolve provider
            provider = key_data.provider
            if isinstance(provider, str):
                provider = Provider.from_string(provider)

            # Encrypt if configured
            key_value = key_data.key_value
            if self._config.encrypt_keys and self._config.shared_secret:
                key_value = encrypt_api_key(key_value, self._config.shared_secret)

            api_key = APIKey(
                provider=provider,
                key_value=key_value,
                alias=key_data.alias,
                daily_limit=key_data.daily_limit or self._config.default_daily_limit,
                monthly_limit=key_data.monthly_limit or self._config.default_monthly_limit,
                max_concurrent=key_data.max_concurrent or self._config.default_max_concurrent,
                environment=key_data.environment,
                metadata=key_data.metadata,
                tags=key_data.tags,
                expires_at=key_data.expires_at,
                weight=key_data.weight,
                priority=key_data.priority,
            )
            api_keys.append(api_key)

        return await self._storage.bulk_add_keys(api_keys)

    async def bulk_delete_keys(
        self,
        key_ids: list[str],
        hard: bool = False,
    ) -> BulkOperationResult:
        """Delete multiple keys at once.

        Args:
            key_ids: List of key IDs to delete.
            hard: If True, permanently delete.

        Returns:
            BulkOperationResult with success/failure counts.
        """
        self._ensure_initialized()
        soft = not hard and self._config.soft_delete
        return await self._storage.bulk_delete_keys(key_ids, soft=soft)

    # ── Health & Info ─────────────────────────────────────────────────────

    async def health_check(self) -> dict[str, Any]:
        """Check if the handler and storage are healthy.

        Returns:
            Dict with health status information.
        """
        storage_ok = False
        if self._initialized:
            try:
                storage_ok = await self._storage.health_check()
            except Exception:
                storage_ok = False

        return {
            "initialized": self._initialized,
            "storage_backend": self._config.storage_backend,
            "storage_healthy": storage_ok,
            "encryption_enabled": self._config.encrypt_keys,
            "rotation_strategy": self._config.rotation_strategy,
        }

    async def info(self) -> dict[str, Any]:
        """Get summary information about the handler.

        Returns:
            Dict with key counts, configuration, and status.
        """
        self._ensure_initialized()

        total_keys = await self._storage.count_keys()
        active_keys = await self._storage.count_keys(status=KeyStatus.ACTIVE)

        return {
            "total_keys": total_keys,
            "active_keys": active_keys,
            "storage_backend": self._config.storage_backend,
            "rotation_strategy": self._config.rotation_strategy,
            "encryption_enabled": self._config.encrypt_keys,
            "auto_reset_counters": self._config.auto_reset_counters,
            "soft_delete": self._config.soft_delete,
        }

    # ── Manual Resets ─────────────────────────────────────────────────────

    async def reset_daily_counts(self) -> int:
        """Manually reset all stale daily counters.

        Returns:
            Number of keys reset.
        """
        self._ensure_initialized()
        assert self._rate_limiter is not None
        return await self._rate_limiter.reset_daily()

    async def reset_monthly_counts(self) -> int:
        """Manually reset all stale monthly counters.

        Returns:
            Number of keys reset.
        """
        self._ensure_initialized()
        assert self._rate_limiter is not None
        return await self._rate_limiter.reset_monthly()

    async def reset_all_concurrent(self) -> int:
        """Reset concurrent usage to 0 for all keys.

        Useful for application startup recovery after crashes.

        Returns:
            Number of keys reset.
        """
        self._ensure_initialized()
        assert self._usage_tracker is not None
        return await self._usage_tracker.reset_all_concurrent()


class SyncAPIServiceHandler:
    """Synchronous wrapper around APIServiceHandler.

    Provides the same API but runs everything through asyncio.run() or
    an existing event loop. Useful for non-async codebases.

    Example::

        handler = SyncAPIServiceHandler(
            storage_backend="sqlite",
            connection_string="sqlite:///keys.db",
        )
        handler.initialize()

        key = handler.add_key(provider="openai", key_value="sk-abc...")
        handler.close()
    """

    def __init__(self, **kwargs: Any) -> None:
        self._async_handler = APIServiceHandler(**kwargs)
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def _run(self, coro):
        """Run an async coroutine synchronously."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # We're inside an async context — use a new thread
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result()
        else:
            return asyncio.run(coro)

    def initialize(self) -> None:
        """Initialize the handler."""
        self._run(self._async_handler.initialize())

    def close(self) -> None:
        """Close the handler."""
        self._run(self._async_handler.close())

    def add_key(self, **kwargs) -> APIKey:
        """Add a new API key."""
        return self._run(self._async_handler.add_key(**kwargs))

    def get_key(self, key_id: str, **kwargs) -> APIKey:
        """Get a key by ID."""
        return self._run(self._async_handler.get_key(key_id, **kwargs))

    def get_keys_by_provider(self, provider, **kwargs) -> list[APIKey]:
        """Get all keys for a provider."""
        return self._run(self._async_handler.get_keys_by_provider(provider, **kwargs))

    def get_all_keys(self, **kwargs) -> list[APIKey]:
        """Get all keys with optional filtering."""
        return self._run(self._async_handler.get_all_keys(**kwargs))

    def update_key(self, key_id: str, **kwargs) -> APIKey:
        """Update a key."""
        return self._run(self._async_handler.update_key(key_id, **kwargs))

    def delete_key(self, key_id: str, **kwargs) -> bool:
        """Delete a key."""
        return self._run(self._async_handler.delete_key(key_id, **kwargs))

    def get_next_key(self, provider, **kwargs) -> APIKey:
        """Get the next available key."""
        return self._run(self._async_handler.get_next_key(provider, **kwargs))

    def record_usage(self, key_id: str, **kwargs) -> None:
        """Record usage for a key."""
        self._run(self._async_handler.record_usage(key_id, **kwargs))

    def get_usage_stats(self, key_id: str) -> UsageStats:
        """Get usage stats for a key."""
        return self._run(self._async_handler.get_usage_stats(key_id))

    def get_concurrent_usage(self, key_id: str) -> int:
        """Get concurrent usage."""
        return self._run(self._async_handler.get_concurrent_usage(key_id))

    def health_check(self) -> dict[str, Any]:
        """Health check."""
        return self._run(self._async_handler.health_check())

    def info(self) -> dict[str, Any]:
        """Get handler info."""
        return self._run(self._async_handler.info())

    def bulk_add_keys(self, keys, **kwargs) -> BulkOperationResult:
        """Bulk add keys."""
        return self._run(self._async_handler.bulk_add_keys(keys, **kwargs))

    def bulk_delete_keys(self, key_ids, **kwargs) -> BulkOperationResult:
        """Bulk delete keys."""
        return self._run(self._async_handler.bulk_delete_keys(key_ids, **kwargs))

    def reset_daily_counts(self) -> int:
        """Reset daily counts."""
        return self._run(self._async_handler.reset_daily_counts())

    def reset_monthly_counts(self) -> int:
        """Reset monthly counts."""
        return self._run(self._async_handler.reset_monthly_counts())

    def reset_all_concurrent(self) -> int:
        """Reset all concurrent usage."""
        return self._run(self._async_handler.reset_all_concurrent())
