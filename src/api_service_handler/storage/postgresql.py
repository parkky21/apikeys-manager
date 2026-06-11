"""PostgreSQL storage backend using asyncpg."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Optional

from ..enums import KeyStatus, Provider
from ..exceptions import DuplicateKeyError, KeyNotFoundError, StorageConnectionError
from ..models import APIKey, BulkOperationResult, KeyFilter, KeyUpdateRequest
from .base import StorageBackend

def _try_import_asyncpg():
    """Lazy import asyncpg with helpful error."""
    try:
        import asyncpg
        return asyncpg
    except ImportError:
        raise ImportError(
            "PostgreSQL backend requires 'asyncpg'. "
            "Install with: pip install api-service-handler[postgresql]"
        )

class PostgreSQLStorageBackend(StorageBackend):
    """PostgreSQL storage backend using asyncpg.

    Enterprise grade relational storage.
    Install with: pip install api-service-handler[postgresql]
    """

    def __init__(self, connection_string: str) -> None:
        """Initialize PostgreSQL backend.

        Args:
            connection_string: PostgreSQL connection URI, e.g., 'postgresql://user:pass@localhost:5432/my_db'.
        """
        self._asyncpg = _try_import_asyncpg()
        # Handle 'postgres://' vs 'postgresql://'
        if connection_string.startswith('postgres://'):
            self._connection_string = 'postgresql://' + connection_string[11:]
        else:
            self._connection_string = connection_string
        self._pool = None
        self._initialized = False

    async def initialize(self) -> None:
        """Create the PostgreSQL connection pool and tables."""
        try:
            self._pool = await self._asyncpg.create_pool(self._connection_string, min_size=2, max_size=10)
            
            async with self._pool.acquire() as conn:
                await conn.execute("""
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
                        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                        tags JSONB NOT NULL DEFAULT '[]'::jsonb,
                        last_used_at TIMESTAMPTZ,
                        last_reset_daily DATE NOT NULL,
                        last_reset_monthly DATE NOT NULL,
                        expires_at TIMESTAMPTZ,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                """)

                # Create indexes
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_api_keys_provider ON api_keys(provider)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_api_keys_status ON api_keys(status)")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_api_keys_provider_status ON api_keys(provider, status)")
                
                # Unique constraint for active keys
                # PostgreSQL requires a partial unique index
                await conn.execute("""
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_pg_api_keys_unique_active 
                    ON api_keys (key_value, provider) 
                    WHERE status != 'revoked'
                """)
                
            self._initialized = True
        except Exception as e:
            raise StorageConnectionError(backend="postgresql", detail=str(e))

    async def close(self) -> None:
        """Close the PostgreSQL connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None
        self._initialized = False

    def _row_to_key(self, row) -> APIKey:
        """Convert a database row to an APIKey model."""
        data = dict(row)
        
        # Parse JSON fields - asyncpg returns strings for JSONB if not configured, or parsed dicts if configured
        if isinstance(data.get("metadata"), str):
            data["metadata"] = json.loads(data["metadata"])
        if isinstance(data.get("tags"), str):
            data["tags"] = json.loads(data["tags"])
            
        # Ensure UTC datetimes
        for dt_field in ("last_used_at", "expires_at", "created_at", "updated_at"):
            if data.get(dt_field):
                dt = data[dt_field]
                if dt.tzinfo is None:
                    data[dt_field] = dt.replace(tzinfo=timezone.utc)
                    
        return APIKey(**data)

    # ── CRUD ───────────────────────────────────────────────────────────────

    async def add_key(self, key: APIKey) -> APIKey:
        provider_val = key.provider.value if hasattr(key.provider, "value") else key.provider
        status_val = key.status.value if hasattr(key.status, "value") else key.status
        env_val = key.environment.value if hasattr(key.environment, "value") else key.environment
        
        async with self._pool.acquire() as conn:
            try:
                await conn.execute(
                    """
                    INSERT INTO api_keys (
                        id, provider, key_value, alias, status, environment,
                        daily_limit, monthly_limit, daily_usage_count, monthly_usage_count, total_usage_count,
                        concurrent_usage, max_concurrent, weight, priority,
                        metadata, tags, last_used_at, last_reset_daily, last_reset_monthly,
                        expires_at, created_at, updated_at
                    ) VALUES (
                        $1, $2, $3, $4, $5, $6,
                        $7, $8, $9, $10, $11,
                        $12, $13, $14, $15,
                        $16::jsonb, $17::jsonb, $18, $19, $20,
                        $21, $22, $23
                    )
                    """,
                    key.id, provider_val, key.key_value, key.alias, status_val, env_val,
                    key.daily_limit, key.monthly_limit, key.daily_usage_count, key.monthly_usage_count, key.total_usage_count,
                    key.concurrent_usage, key.max_concurrent, key.weight, key.priority,
                    json.dumps(key.metadata), json.dumps(key.tags), key.last_used_at, key.last_reset_daily, key.last_reset_monthly,
                    key.expires_at, key.created_at, key.updated_at
                )
                return key
            except self._asyncpg.exceptions.UniqueViolationError:
                raise DuplicateKeyError(provider=provider_val, key_value=key.key_value)

    async def get_key(self, key_id: str) -> APIKey:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM api_keys WHERE id = $1", key_id)
            if not row:
                raise KeyNotFoundError(key_id=key_id)
            return self._row_to_key(row)

    async def get_keys_by_provider(self, provider: Provider) -> list[APIKey]:
        provider_val = provider.value if hasattr(provider, "value") else provider
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM api_keys WHERE provider = $1", provider_val)
            return [self._row_to_key(row) for row in rows]

    async def get_all_keys(self, key_filter: Optional[KeyFilter] = None) -> list[APIKey]:
        query = "SELECT * FROM api_keys"
        conditions = []
        args = []
        idx = 1
        
        if key_filter:
            if key_filter.provider is not None:
                provider_val = key_filter.provider.value if hasattr(key_filter.provider, "value") else key_filter.provider
                conditions.append(f"provider = ${idx}")
                args.append(provider_val)
                idx += 1
            if key_filter.status is not None:
                status_val = key_filter.status.value if hasattr(key_filter.status, "value") else key_filter.status
                conditions.append(f"status = ${idx}")
                args.append(status_val)
                idx += 1
            if key_filter.environment is not None:
                env_val = key_filter.environment.value if hasattr(key_filter.environment, "value") else key_filter.environment
                conditions.append(f"environment = ${idx}")
                args.append(env_val)
                idx += 1
            if key_filter.alias_contains:
                conditions.append(f"alias ILIKE ${idx}")
                args.append(f"%{key_filter.alias_contains}%")
                idx += 1
                
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
            
        query += " ORDER BY priority ASC, created_at ASC"

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
            keys = [self._row_to_key(row) for row in rows]
            
        # In-memory filtering for JSON/complex checks (could be moved to SQL later for optimization)
        if key_filter:
            if key_filter.tags:
                keys = [k for k in keys if any(tag in k.tags for tag in key_filter.tags)]
            if key_filter.metadata_filter:
                keys = [k for k in keys if all(k.metadata.get(mk) == mv for mk, mv in key_filter.metadata_filter.items())]
            if key_filter.has_capacity is not None:
                keys = [k for k in keys if k.has_capacity == key_filter.has_capacity]
                
        return keys

    async def update_key(self, key_id: str, updates: KeyUpdateRequest) -> APIKey:
        # Check exists
        await self.get_key(key_id)
        
        update_data = updates.model_dump(exclude_unset=True)
        if not update_data:
            return await self.get_key(key_id)
            
        update_data["updated_at"] = datetime.now(timezone.utc)
        
        # Format complex types
        if "metadata" in update_data:
            update_data["metadata"] = json.dumps(update_data["metadata"])
        if "tags" in update_data:
            update_data["tags"] = json.dumps(update_data["tags"])
        if "status" in update_data:
            val = update_data["status"]
            update_data["status"] = val.value if hasattr(val, "value") else val
        if "environment" in update_data:
            val = update_data["environment"]
            update_data["environment"] = val.value if hasattr(val, "value") else val
            
        set_clauses = []
        args = []
        idx = 1
        
        for k, v in update_data.items():
            if k in ("metadata", "tags"):
                set_clauses.append(f"{k} = ${idx}::jsonb")
            else:
                set_clauses.append(f"{k} = ${idx}")
            args.append(v)
            idx += 1
            
        args.append(key_id)
        query = f"UPDATE api_keys SET {', '.join(set_clauses)} WHERE id = ${idx}"
        
        async with self._pool.acquire() as conn:
            await conn.execute(query, *args)
            
        return await self.get_key(key_id)

    async def delete_key(self, key_id: str, soft: bool = True) -> bool:
        await self.get_key(key_id)
        
        async with self._pool.acquire() as conn:
            if soft:
                now = datetime.now(timezone.utc)
                await conn.execute("UPDATE api_keys SET status = 'revoked', updated_at = $1 WHERE id = $2", now, key_id)
            else:
                await conn.execute("DELETE FROM api_keys WHERE id = $1", key_id)
                
        return True

    # ── Usage Tracking ─────────────────────────────────────────────────────

    async def increment_usage(
        self,
        key_id: str,
        daily: int = 1,
        monthly: int = 1,
        total: int = 1,
    ) -> None:
        now = datetime.now(timezone.utc)
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE api_keys 
                SET daily_usage_count = daily_usage_count + $1,
                    monthly_usage_count = monthly_usage_count + $2,
                    total_usage_count = total_usage_count + $3,
                    last_used_at = $4,
                    updated_at = $5
                WHERE id = $6
                """,
                daily, monthly, total, now, now, key_id
            )

    async def update_concurrent_usage(self, key_id: str, delta: int) -> int:
        now = datetime.now(timezone.utc)
        async with self._pool.acquire() as conn:
            # Use RETURNING to get the updated value
            row = await conn.fetchrow(
                """
                UPDATE api_keys 
                SET concurrent_usage = GREATEST(0, concurrent_usage + $1),
                    updated_at = $2
                WHERE id = $3
                RETURNING concurrent_usage
                """,
                delta, now, key_id
            )
            if not row:
                raise KeyNotFoundError(key_id=key_id)
            return row["concurrent_usage"]

    async def reset_daily_counts(self, before_date: date) -> int:
        now = datetime.now(timezone.utc)
        
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE api_keys 
                SET daily_usage_count = 0,
                    last_reset_daily = $1,
                    updated_at = $2
                WHERE last_reset_daily < $1
                """,
                before_date, now
            )
            
            # Re-activate rate-limited keys
            await conn.execute(
                """
                UPDATE api_keys
                SET status = 'active'
                WHERE status = 'rate_limited'
                  AND (monthly_limit IS NULL OR monthly_usage_count < monthly_limit)
                """
            )
            
            return int(result.split()[-1]) if result.startswith("UPDATE") else 0

    async def reset_monthly_counts(self, before_date: date) -> int:
        now = datetime.now(timezone.utc)
        
        async with self._pool.acquire() as conn:
            # PostgreSQL EXTRACT is useful here
            result = await conn.execute(
                """
                UPDATE api_keys 
                SET monthly_usage_count = 0,
                    last_reset_monthly = $1,
                    status = CASE WHEN status = 'rate_limited' THEN 'active' ELSE status END,
                    updated_at = $2
                WHERE EXTRACT(MONTH FROM last_reset_monthly) != EXTRACT(MONTH FROM $1::date)
                   OR EXTRACT(YEAR FROM last_reset_monthly) != EXTRACT(YEAR FROM $1::date)
                """,
                before_date, now
            )
            
            return int(result.split()[-1]) if result.startswith("UPDATE") else 0

    async def update_last_used(self, key_id: str) -> None:
        now = datetime.now(timezone.utc)
        async with self._pool.acquire() as conn:
            await conn.execute("UPDATE api_keys SET last_used_at = $1, updated_at = $1 WHERE id = $2", now, key_id)

    # ── Bulk Operations ────────────────────────────────────────────────────

    async def bulk_add_keys(self, keys: list[APIKey]) -> BulkOperationResult:
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
        if not self._pool or not self._initialized:
            return False
        try:
            async with self._pool.acquire() as conn:
                await conn.execute("SELECT 1")
            return True
        except Exception:
            return False

    async def count_keys(
        self,
        provider: Optional[Provider] = None,
        status: Optional[KeyStatus] = None,
    ) -> int:
        query = "SELECT COUNT(*) FROM api_keys"
        conditions = []
        args = []
        idx = 1
        
        if provider is not None:
            provider_val = provider.value if hasattr(provider, "value") else provider
            conditions.append(f"provider = ${idx}")
            args.append(provider_val)
            idx += 1
        if status is not None:
            status_val = status.value if hasattr(status, "value") else status
            conditions.append(f"status = ${idx}")
            args.append(status_val)
            idx += 1
            
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
            
        async with self._pool.acquire() as conn:
            return await conn.fetchval(query, *args)
