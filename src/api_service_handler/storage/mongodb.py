"""MongoDB storage backend using motor."""

from __future__ import annotations

import copy
from datetime import date, datetime, timezone
from typing import Any, Optional

from ..enums import KeyStatus, Provider
from ..exceptions import DuplicateKeyError, KeyNotFoundError, StorageConnectionError
from ..models import APIKey, BulkOperationResult, KeyFilter, KeyUpdateRequest
from .base import StorageBackend

def _try_import_motor():
    """Lazy import motor with helpful error."""
    try:
        import motor.motor_asyncio
        return motor.motor_asyncio
    except ImportError:
        raise ImportError(
            "MongoDB backend requires 'motor'. "
            "Install with: pip install api-service-handler[mongodb]"
        )

class MongoDBStorageBackend(StorageBackend):
    """MongoDB storage backend using motor.

    Good for highly scalable, document-oriented storage.
    Install with: pip install api-service-handler[mongodb]
    """

    def __init__(self, connection_string: str) -> None:
        """Initialize MongoDB backend.

        Args:
            connection_string: MongoDB connection URI, e.g., 'mongodb://localhost:27017/my_db'.
        """
        self._motor = _try_import_motor()
        self._connection_string = connection_string
        self._client = None
        self._db = None
        self._collection = None
        self._initialized = False

    async def initialize(self) -> None:
        """Connect to MongoDB and setup indexes."""
        try:
            self._client = self._motor.AsyncIOMotorClient(self._connection_string)
            
            # Extract database name from URI, default to api_service_handler
            db_name = self._client.get_database().name if self._client.get_database().name else "api_service_handler"
            self._db = self._client[db_name]
            self._collection = self._db["api_keys"]

            # Create indexes
            import pymongo
            
            # Provider index
            await self._collection.create_index([("provider", pymongo.ASCENDING)])
            
            # Status index
            await self._collection.create_index([("status", pymongo.ASCENDING)])
            
            # Compound provider/status index
            await self._collection.create_index(
                [("provider", pymongo.ASCENDING), ("status", pymongo.ASCENDING)]
            )
            
            # Compound index for metadata client_id filters
            await self._collection.create_index(
                [
                    ("provider", pymongo.ASCENDING), 
                    ("status", pymongo.ASCENDING), 
                    ("metadata.client_id", pymongo.ASCENDING)
                ]
            )
            
            # Unique compound index for active keys to prevent duplicates
            try:
                await self._collection.create_index(
                    [("key_value", pymongo.ASCENDING), ("provider", pymongo.ASCENDING)],
                    unique=True,
                    partialFilterExpression={"status": {"$ne": "revoked"}}
                )
            except pymongo.errors.OperationFailure:
                # Fallback for AWS DocumentDB which does not support $ne in partial index
                await self._collection.create_index(
                    [("key_value", pymongo.ASCENDING), ("provider", pymongo.ASCENDING)],
                    unique=True
                )

            self._initialized = True
        except Exception as e:
            raise StorageConnectionError(backend="mongodb", detail=str(e))

    async def close(self) -> None:
        """Close the MongoDB connection."""
        if self._client:
            self._client.close()
            self._client = None
            self._db = None
            self._collection = None
        self._initialized = False

    def _dict_to_key(self, doc: dict[str, Any]) -> APIKey:
        """Convert a MongoDB document to an APIKey model."""
        if not doc:
            return None
        
        # Map _id to id
        if "_id" in doc:
            doc["id"] = str(doc.pop("_id"))
            
        return APIKey(**doc)

    def _key_to_dict(self, key: APIKey) -> dict[str, Any]:
        """Convert an APIKey model to a MongoDB document."""
        data = key.model_dump()
        
        # Handle enums
        data["provider"] = data["provider"].value if hasattr(data["provider"], "value") else data["provider"]
        data["status"] = data["status"].value if hasattr(data["status"], "value") else data["status"]
        data["environment"] = data["environment"].value if hasattr(data["environment"], "value") else data["environment"]
        
        # MongoDB native datetime is UTC, but APIKey stores datetimes. We can dump to standard formats.
        # Ensure datetimes are proper datetime objects for MongoDB
        # pydantic model_dump handles basic types, but we want proper dates
        # model_dump might convert dates to strings or leave as dates.
        # Let's ensure proper MongoDB types
        
        # map id to _id
        data["_id"] = data.pop("id")
        
        # Datetimes and dates are naturally handled by motor/pymongo if they are datetime objects,
        # but pydantic might leave them. Let's ensure they are native types.
        for field in ["last_used_at", "expires_at", "created_at", "updated_at"]:
            if data.get(field) and isinstance(data[field], str):
                data[field] = datetime.fromisoformat(data[field])
        
        for field in ["last_reset_daily", "last_reset_monthly"]:
            if data.get(field) and isinstance(data[field], str):
                data[field] = datetime.fromisoformat(data[field]).date()
            # pymongo requires datetime for dates too usually, convert date to datetime
            if data.get(field) and isinstance(data[field], date) and not isinstance(data[field], datetime):
                data[field] = datetime.combine(data[field], datetime.min.time(), tzinfo=timezone.utc)

        return data

    # ── CRUD ───────────────────────────────────────────────────────────────

    async def add_key(self, key: APIKey) -> APIKey:
        doc = self._key_to_dict(key)
        try:
            await self._collection.insert_one(doc)
            return key
        except self._motor.pymongo.errors.DuplicateKeyError:
            provider_val = key.provider.value if isinstance(key.provider, Provider) else key.provider
            raise DuplicateKeyError(provider=provider_val, key_value=key.key_value)

    async def get_key(self, key_id: str) -> APIKey:
        doc = await self._collection.find_one({"_id": key_id})
        if not doc:
            raise KeyNotFoundError(key_id=key_id)
        return self._dict_to_key(doc)

    async def get_keys_by_provider(self, provider: Provider) -> list[APIKey]:
        provider_val = provider.value if isinstance(provider, Provider) else provider
        cursor = self._collection.find({"provider": provider_val})
        return [self._dict_to_key(doc) async for doc in cursor]

    async def get_all_keys(self, key_filter: Optional[KeyFilter] = None) -> list[APIKey]:
        query = {}
        
        if key_filter:
            if key_filter.provider is not None:
                provider_val = key_filter.provider.value if isinstance(key_filter.provider, Provider) else key_filter.provider
                query["provider"] = provider_val
            if key_filter.status is not None:
                status_val = key_filter.status.value if isinstance(key_filter.status, KeyStatus) else key_filter.status
                query["status"] = status_val
            if key_filter.environment is not None:
                env_val = key_filter.environment.value if hasattr(key_filter.environment, "value") else key_filter.environment
                query["environment"] = env_val
            if key_filter.alias_contains:
                query["alias"] = {"$regex": key_filter.alias_contains, "$options": "i"}
            if key_filter.tags:
                query["tags"] = {"$in": key_filter.tags}
            if key_filter.metadata_filter:
                for k, v in key_filter.metadata_filter.items():
                    query[f"metadata.{k}"] = v

        # Sorting logic: priority asc, created_at asc
        cursor = self._collection.find(query).sort([("priority", 1), ("created_at", 1)])
        keys = [self._dict_to_key(doc) async for doc in cursor]
        
        # Capacity filter applies in memory
        if key_filter and key_filter.has_capacity is not None:
            keys = [k for k in keys if k.has_capacity == key_filter.has_capacity]
            
        return keys

    async def update_key(self, key_id: str, updates: KeyUpdateRequest) -> APIKey:
        # Check exists
        await self.get_key(key_id)
        
        update_data = updates.model_dump(exclude_unset=True)
        if not update_data:
            return await self.get_key(key_id)
            
        # Handle enums
        if "status" in update_data:
            val = update_data["status"]
            update_data["status"] = val.value if hasattr(val, "value") else val
        if "environment" in update_data:
            val = update_data["environment"]
            update_data["environment"] = val.value if hasattr(val, "value") else val
            
        # Handle datetimes
        if "expires_at" in update_data and update_data["expires_at"]:
            if isinstance(update_data["expires_at"], str):
                update_data["expires_at"] = datetime.fromisoformat(update_data["expires_at"])
                
        update_data["updated_at"] = datetime.now(timezone.utc)
        
        await self._collection.update_one({"_id": key_id}, {"$set": update_data})
        return await self.get_key(key_id)

    async def delete_key(self, key_id: str, soft: bool = True) -> bool:
        await self.get_key(key_id)
        
        if soft:
            now = datetime.now(timezone.utc)
            await self._collection.update_one(
                {"_id": key_id},
                {"$set": {"status": "revoked", "updated_at": now}}
            )
        else:
            await self._collection.delete_one({"_id": key_id})
            
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
        await self._collection.update_one(
            {"_id": key_id},
            {
                "$inc": {
                    "daily_usage_count": daily,
                    "monthly_usage_count": monthly,
                    "total_usage_count": total
                },
                "$set": {
                    "last_used_at": now,
                    "updated_at": now
                }
            }
        )

    async def update_concurrent_usage(self, key_id: str, delta: int) -> int:
        now = datetime.now(timezone.utc)
        # Use find_one_and_update to ensure we don't go below 0 and get the updated value
        # First query current to see if delta brings it below 0
        doc = await self._collection.find_one({"_id": key_id}, {"concurrent_usage": 1})
        if not doc:
            raise KeyNotFoundError(key_id=key_id)
            
        current = doc.get("concurrent_usage", 0)
        actual_delta = delta
        if current + delta < 0:
            actual_delta = -current
            
        import pymongo
        updated = await self._collection.find_one_and_update(
            {"_id": key_id},
            {
                "$inc": {"concurrent_usage": actual_delta},
                "$set": {"updated_at": now}
            },
            return_document=pymongo.ReturnDocument.AFTER
        )
        return updated.get("concurrent_usage", 0)

    async def reset_daily_counts(self, before_date: date) -> int:
        now = datetime.now(timezone.utc)
        before_dt = datetime.combine(before_date, datetime.min.time(), tzinfo=timezone.utc)
        
        result = await self._collection.update_many(
            {"last_reset_daily": {"$lt": before_dt}},
            {
                "$set": {
                    "daily_usage_count": 0,
                    "last_reset_daily": before_dt,
                    "updated_at": now
                }
            }
        )
        
        # Recover rate-limited keys if monthly is ok
        # For simplicity, we fetch rate_limited keys and check them
        # It's harder to do a complex conditionally-update-many in Mongo based on other fields
        cursor = self._collection.find({"status": "rate_limited"})
        async for doc in cursor:
            monthly_limit = doc.get("monthly_limit")
            monthly_count = doc.get("monthly_usage_count", 0)
            if monthly_limit is None or monthly_count < monthly_limit:
                # also check daily, but we just reset it
                daily_limit = doc.get("daily_limit")
                daily_count = doc.get("daily_usage_count", 0)
                if daily_limit is None or daily_count < daily_limit:
                    await self._collection.update_one(
                        {"_id": doc["_id"]},
                        {"$set": {"status": "active", "updated_at": now}}
                    )

        return result.modified_count

    async def reset_monthly_counts(self, before_date: date) -> int:
        now = datetime.now(timezone.utc)
        before_dt = datetime.combine(before_date, datetime.min.time(), tzinfo=timezone.utc)
        
        # To reset correctly, we need to find keys where month or year differs
        # MongoDB aggregation would be complex, let's just fetch last_reset_monthly
        cursor = self._collection.find({}, {"_id": 1, "last_reset_monthly": 1, "status": 1})
        ids_to_reset = []
        async for doc in cursor:
            last_reset = doc.get("last_reset_monthly")
            if last_reset:
                if isinstance(last_reset, datetime):
                    last_reset_date = last_reset.date()
                else:
                    last_reset_date = date.fromisoformat(last_reset) if isinstance(last_reset, str) else last_reset
                    
                if last_reset_date.month != before_date.month or last_reset_date.year != before_date.year:
                    ids_to_reset.append(doc["_id"])
                    
        if not ids_to_reset:
            return 0
            
        await self._collection.update_many(
            {"_id": {"$in": ids_to_reset}},
            {
                "$set": {
                    "monthly_usage_count": 0,
                    "last_reset_monthly": before_dt,
                    "updated_at": now
                }
            }
        )
        
        # Recover rate-limited
        await self._collection.update_many(
            {"_id": {"$in": ids_to_reset}, "status": "rate_limited"},
            {"$set": {"status": "active", "updated_at": now}}
        )
        
        return len(ids_to_reset)

    async def update_last_used(self, key_id: str) -> None:
        now = datetime.now(timezone.utc)
        await self._collection.update_one(
            {"_id": key_id},
            {"$set": {"last_used_at": now, "updated_at": now}}
        )

    # ── Bulk Operations ────────────────────────────────────────────────────

    async def bulk_add_keys(self, keys: list[APIKey]) -> BulkOperationResult:
        result = BulkOperationResult(total=len(keys))
        
        if not keys:
            return result
            
        # For bulk add, doing one by one to catch individual errors and not fail all
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
        
        if not key_ids:
            return result
            
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
        if not self._client or not self._initialized:
            return False
        try:
            await self._client.admin.command('ping')
            return True
        except Exception:
            return False

    async def count_keys(
        self,
        provider: Optional[Provider] = None,
        status: Optional[KeyStatus] = None,
    ) -> int:
        query = {}
        if provider is not None:
            query["provider"] = provider.value if hasattr(provider, "value") else provider
        if status is not None:
            query["status"] = status.value if hasattr(status, "value") else status
            
        return await self._collection.count_documents(query)
