"""SQLite storage backend using aiosqlite."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Optional

from ..enums import Provider, KeyStatus
from ..exceptions import KeyNotFoundError, DuplicateKeyError, StorageConnectionError
from ..models import APIKey, KeyFilter, KeyUpdateRequest, BulkOperationResult
from .base import StorageBackend


def _try_import_aiosqlite():
    """Lazy import aiosqlite with helpful error."""
    try:
        import aiosqlite
        return aiosqlite
    except ImportError:
        raise ImportError(
            "SQLite backend requires 'aiosqlite'. "
            "Install with: pip install api-service-handler[sqlite]"
        )


class SQLiteStorageBackend(StorageBackend):
    """SQLite storage backend using aiosqlite.

    Good default for single-service deployments and development.
    Install with: pip install api-service-handler[sqlite]
    """

    def __init__(self, connection_string: str) -> None:
        """Initialize SQLite backend.

        Args:
            connection_string: Path to SQLite DB file, e.g., 'sqlite:///keys.db' or '/path/to/keys.db'.
        """
        self._aiosqlite = _try_import_aiosqlite()
        # Strip sqlite:/// prefix if present
        if connection_string.startswith("sqlite:///"):
            self._db_path = connection_string[len("sqlite:///"):]
        elif connection_string.startswith("sqlite://"):
            self._db_path = connection_string[len("sqlite://"):]
        else:
            self._db_path = connection_string
        self._db = None
        self._initialized = False

    async def initialize(self) -> None:
        """Create the SQLite database and tables."""
        try:
            self._db = await self._aiosqlite.connect(self._db_path)
            await self._db.execute("PRAGMA journal_mode=WAL")
            await self._db.execute("PRAGMA foreign_keys=ON")

            await self._db.execute("""
                CREATE TABLE IF NOT EXISTS api_keys (
                    id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    key_value TEXT NOT NULL,
                    alias TEXT,
                    status TEXT NOT NULL DEFAULT 'active',
                    environment TEXT NOT NULL DEFAULT 'production',
                    daily_limit INTEGER,
                    monthly_limit INTEGER,
                    daily_usage_count INTEGER NOT NULL DEFAULT 0,
                    monthly_usage_count INTEGER NOT NULL DEFAULT 0,
                    total_usage_count INTEGER NOT NULL DEFAULT 0,
                    concurrent_usage INTEGER NOT NULL DEFAULT 0,
                    max_concurrent INTEGER,
                    weight INTEGER NOT NULL DEFAULT 1,
                    priority INTEGER NOT NULL DEFAULT 0,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    tags TEXT NOT NULL DEFAULT '[]',
                    last_used_at TEXT,
                    last_reset_daily TEXT NOT NULL,
                    last_reset_monthly TEXT NOT NULL,
                    expires_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            await self._db.execute(
                "CREATE INDEX IF NOT EXISTS idx_api_keys_provider ON api_keys(provider)"
            )
            await self._db.execute(
                "CREATE INDEX IF NOT EXISTS idx_api_keys_status ON api_keys(status)"
            )
            await self._db.execute(
                "CREATE INDEX IF NOT EXISTS idx_api_keys_provider_status ON api_keys(provider, status)"
            )

            await self._db.commit()
            self._initialized = True

        except Exception as e:
            raise StorageConnectionError(backend="sqlite", details=str(e))

    async def close(self) -> None:
        """Close the SQLite connection."""
        if self._db:
            await self._db.close()
            self._db = None
        self._initialized = False

    def _row_to_key(self, row: dict) -> APIKey:
        """Convert a database row to an APIKey model."""
        data = dict(row)
        # Parse JSON fields
        data["metadata"] = json.loads(data.get("metadata", "{}"))
        data["tags"] = json.loads(data.get("tags", "[]"))

        # Parse datetime fields
        for dt_field in ("last_used_at", "expires_at", "created_at", "updated_at"):
            if data.get(dt_field):
                data[dt_field] = datetime.fromisoformat(data[dt_field])
            elif dt_field in ("created_at", "updated_at"):
                data[dt_field] = datetime.now(timezone.utc)

        # Parse date fields
        for d_field in ("last_reset_daily", "last_reset_monthly"):
            if data.get(d_field):
                data[d_field] = date.fromisoformat(data[d_field])
            else:
                data[d_field] = date.today()

        return APIKey(**data)

    def _key_to_params(self, key: APIKey) -> dict:
        """Convert an APIKey model to SQLite insert parameters."""
        return {
            "id": key.id,
            "provider": key.provider.value if isinstance(key.provider, Provider) else key.provider,
            "key_value": key.key_value,
            "alias": key.alias,
            "status": key.status.value if isinstance(key.status, KeyStatus) else key.status,
            "environment": key.environment.value if hasattr(key.environment, "value") else key.environment,
            "daily_limit": key.daily_limit,
            "monthly_limit": key.monthly_limit,
            "daily_usage_count": key.daily_usage_count,
            "monthly_usage_count": key.monthly_usage_count,
            "total_usage_count": key.total_usage_count,
            "concurrent_usage": key.concurrent_usage,
            "max_concurrent": key.max_concurrent,
            "weight": key.weight,
            "priority": key.priority,
            "metadata": json.dumps(key.metadata),
            "tags": json.dumps(key.tags),
            "last_used_at": key.last_used_at.isoformat() if key.last_used_at else None,
            "last_reset_daily": key.last_reset_daily.isoformat(),
            "last_reset_monthly": key.last_reset_monthly.isoformat(),
            "expires_at": key.expires_at.isoformat() if key.expires_at else None,
            "created_at": key.created_at.isoformat(),
            "updated_at": key.updated_at.isoformat(),
        }

    # ── CRUD ───────────────────────────────────────────────────────────────

    async def add_key(self, key: APIKey) -> APIKey:
        """Insert a new key into SQLite."""
        # Check for duplicates
        provider_val = key.provider.value if isinstance(key.provider, Provider) else key.provider
        async with self._db.execute(
            "SELECT id FROM api_keys WHERE key_value = ? AND provider = ? AND status != 'revoked'",
            (key.key_value, provider_val),
        ) as cursor:
            if await cursor.fetchone():
                raise DuplicateKeyError(provider=provider_val, key_value=key.key_value)

        params = self._key_to_params(key)
        columns = ", ".join(params.keys())
        placeholders = ", ".join(f":{k}" for k in params.keys())

        await self._db.execute(
            f"INSERT INTO api_keys ({columns}) VALUES ({placeholders})",
            params,
        )
        await self._db.commit()
        return key

    async def get_key(self, key_id: str) -> APIKey:
        """Get a key by ID."""
        self._db.row_factory = self._aiosqlite.Row
        async with self._db.execute(
            "SELECT * FROM api_keys WHERE id = ?", (key_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                raise KeyNotFoundError(key_id=key_id)
            return self._row_to_key(dict(row))

    async def get_keys_by_provider(self, provider: Provider) -> list[APIKey]:
        """Get all keys for a provider."""
        provider_val = provider.value if isinstance(provider, Provider) else provider
        self._db.row_factory = self._aiosqlite.Row
        async with self._db.execute(
            "SELECT * FROM api_keys WHERE provider = ?", (provider_val,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_key(dict(row)) for row in rows]

    async def get_all_keys(self, key_filter: Optional[KeyFilter] = None) -> list[APIKey]:
        """Get all keys with optional filtering."""
        self._db.row_factory = self._aiosqlite.Row

        query = "SELECT * FROM api_keys"
        params: list = []
        conditions: list[str] = []

        if key_filter:
            if key_filter.provider is not None:
                provider_val = (
                    key_filter.provider.value
                    if isinstance(key_filter.provider, Provider)
                    else key_filter.provider
                )
                conditions.append("provider = ?")
                params.append(provider_val)
            if key_filter.status is not None:
                status_val = (
                    key_filter.status.value
                    if isinstance(key_filter.status, KeyStatus)
                    else key_filter.status
                )
                conditions.append("status = ?")
                params.append(status_val)
            if key_filter.environment is not None:
                env_val = (
                    key_filter.environment.value
                    if hasattr(key_filter.environment, "value")
                    else key_filter.environment
                )
                conditions.append("environment = ?")
                params.append(env_val)
            if key_filter.alias_contains:
                conditions.append("alias LIKE ?")
                params.append(f"%{key_filter.alias_contains}%")

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY priority ASC, created_at ASC"

        async with self._db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            keys = [self._row_to_key(dict(row)) for row in rows]

        # Apply in-memory filters that can't be done in SQL easily
        if key_filter:
            if key_filter.tags:
                keys = [
                    k for k in keys
                    if any(tag in k.tags for tag in key_filter.tags)
                ]
            if key_filter.metadata_filter:
                keys = [
                    k for k in keys
                    if all(
                        k.metadata.get(mk) == mv
                        for mk, mv in key_filter.metadata_filter.items()
                    )
                ]
            if key_filter.has_capacity:
                keys = [k for k in keys if k.has_capacity]

        return keys

    async def update_key(self, key_id: str, updates: KeyUpdateRequest) -> APIKey:
        """Update a key's fields."""
        # Verify key exists
        await self.get_key(key_id)

        update_data = updates.model_dump(exclude_unset=True)
        if not update_data:
            return await self.get_key(key_id)

        update_data["updated_at"] = datetime.now(timezone.utc).isoformat()

        # Serialize complex fields
        if "metadata" in update_data:
            update_data["metadata"] = json.dumps(update_data["metadata"])
        if "tags" in update_data:
            update_data["tags"] = json.dumps(update_data["tags"])
        if "expires_at" in update_data and update_data["expires_at"]:
            update_data["expires_at"] = update_data["expires_at"].isoformat()
        if "status" in update_data:
            val = update_data["status"]
            update_data["status"] = val.value if hasattr(val, "value") else val
        if "environment" in update_data:
            val = update_data["environment"]
            update_data["environment"] = val.value if hasattr(val, "value") else val

        set_clause = ", ".join(f"{k} = :{k}" for k in update_data.keys())
        update_data["_id"] = key_id

        await self._db.execute(
            f"UPDATE api_keys SET {set_clause} WHERE id = :_id",
            update_data,
        )
        await self._db.commit()
        return await self.get_key(key_id)

    async def delete_key(self, key_id: str, soft: bool = True) -> bool:
        """Delete or revoke a key."""
        await self.get_key(key_id)  # Verify exists

        if soft:
            now = datetime.now(timezone.utc).isoformat()
            await self._db.execute(
                "UPDATE api_keys SET status = 'revoked', updated_at = ? WHERE id = ?",
                (now, key_id),
            )
        else:
            await self._db.execute("DELETE FROM api_keys WHERE id = ?", (key_id,))

        await self._db.commit()
        return True

    # ── Usage Tracking ─────────────────────────────────────────────────────

    async def increment_usage(
        self,
        key_id: str,
        daily: int = 1,
        monthly: int = 1,
        total: int = 1,
    ) -> None:
        """Atomically increment usage counters."""
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            """
            UPDATE api_keys
            SET daily_usage_count = daily_usage_count + ?,
                monthly_usage_count = monthly_usage_count + ?,
                total_usage_count = total_usage_count + ?,
                last_used_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (daily, monthly, total, now, now, key_id),
        )
        await self._db.commit()

    async def update_concurrent_usage(self, key_id: str, delta: int) -> int:
        """Adjust concurrent usage."""
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            """
            UPDATE api_keys
            SET concurrent_usage = MAX(0, concurrent_usage + ?),
                updated_at = ?
            WHERE id = ?
            """,
            (delta, now, key_id),
        )
        await self._db.commit()

        self._db.row_factory = self._aiosqlite.Row
        async with self._db.execute(
            "SELECT concurrent_usage FROM api_keys WHERE id = ?", (key_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                raise KeyNotFoundError(key_id=key_id)
            return row["concurrent_usage"]

    async def reset_daily_counts(self, before_date: date) -> int:
        """Reset daily counts."""
        before_str = before_date.isoformat()
        now = datetime.now(timezone.utc).isoformat()

        cursor = await self._db.execute(
            """
            UPDATE api_keys
            SET daily_usage_count = 0,
                last_reset_daily = ?,
                updated_at = ?
            WHERE last_reset_daily < ?
            """,
            (before_str, now, before_str),
        )
        # Recover rate-limited keys if monthly is ok
        await self._db.execute(
            """
            UPDATE api_keys
            SET status = 'active'
            WHERE status = 'rate_limited'
              AND (monthly_limit IS NULL OR monthly_usage_count < monthly_limit)
            """,
        )
        await self._db.commit()
        return cursor.rowcount

    async def reset_monthly_counts(self, before_date: date) -> int:
        """Reset monthly counts."""
        before_str = before_date.isoformat()
        now = datetime.now(timezone.utc).isoformat()

        # Get keys that need reset (different month/year)
        self._db.row_factory = self._aiosqlite.Row
        async with self._db.execute(
            "SELECT id, last_reset_monthly FROM api_keys"
        ) as cursor:
            rows = await cursor.fetchall()

        ids_to_reset = []
        for row in rows:
            last_reset = date.fromisoformat(row["last_reset_monthly"])
            if last_reset.month != before_date.month or last_reset.year != before_date.year:
                ids_to_reset.append(row["id"])

        if not ids_to_reset:
            return 0

        placeholders = ",".join("?" for _ in ids_to_reset)
        await self._db.execute(
            f"""
            UPDATE api_keys
            SET monthly_usage_count = 0,
                last_reset_monthly = ?,
                status = CASE WHEN status = 'rate_limited' THEN 'active' ELSE status END,
                updated_at = ?
            WHERE id IN ({placeholders})
            """,
            [before_str, now] + ids_to_reset,
        )
        await self._db.commit()
        return len(ids_to_reset)

    async def update_last_used(self, key_id: str) -> None:
        """Update last_used_at."""
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            "UPDATE api_keys SET last_used_at = ?, updated_at = ? WHERE id = ?",
            (now, now, key_id),
        )
        await self._db.commit()

    # ── Bulk Operations ────────────────────────────────────────────────────

    async def bulk_add_keys(self, keys: list[APIKey]) -> BulkOperationResult:
        """Insert multiple keys."""
        result = BulkOperationResult(total=len(keys))

        for key in keys:
            try:
                await self.add_key(key)
                result.successful += 1
                result.created_ids.append(key.id)
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
        """Check SQLite is accessible."""
        if not self._db or not self._initialized:
            return False
        try:
            async with self._db.execute("SELECT 1") as cursor:
                await cursor.fetchone()
            return True
        except Exception:
            return False

    async def count_keys(
        self,
        provider: Optional[Provider] = None,
        status: Optional[KeyStatus] = None,
    ) -> int:
        """Count keys matching criteria."""
        query = "SELECT COUNT(*) as cnt FROM api_keys"
        params: list = []
        conditions: list[str] = []

        if provider is not None:
            provider_val = provider.value if isinstance(provider, Provider) else provider
            conditions.append("provider = ?")
            params.append(provider_val)
        if status is not None:
            status_val = status.value if isinstance(status, KeyStatus) else status
            conditions.append("status = ?")
            params.append(status_val)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        self._db.row_factory = self._aiosqlite.Row
        async with self._db.execute(query, params) as cursor:
            row = await cursor.fetchone()
            return row["cnt"] if row else 0
