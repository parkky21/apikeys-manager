import os
import tempfile
import pytest
from datetime import datetime, timezone, timedelta
from api_service_handler.storage.sqlite import SQLiteStorageBackend
from api_service_handler.models import APIKey, KeyUpdateRequest, KeyFilter
from api_service_handler.exceptions import KeyNotFoundError, DuplicateKeyError

@pytest.fixture
async def sqlite_backend():
    fd, path = tempfile.mkstemp()
    os.close(fd)
    
    backend = SQLiteStorageBackend(f"sqlite:///{path}")
    await backend.initialize()
    yield backend
    await backend.close()
    
    if os.path.exists(path):
        os.unlink(path)

@pytest.mark.asyncio
async def test_sqlite_crud(sqlite_backend):
    key = APIKey(provider="openai", key_value="sk-test", alias="test1")
    added = await sqlite_backend.add_key(key)
    
    assert added.id is not None
    
    # Get
    fetched = await sqlite_backend.get_key(added.id)
    assert fetched.key_value == "sk-test"
    
    # Duplicate
    with pytest.raises(DuplicateKeyError):
        await sqlite_backend.add_key(APIKey(provider="openai", key_value="sk-test"))
    
    # Update
    updated = await sqlite_backend.update_key(added.id, KeyUpdateRequest(alias="test2"))
    assert updated.alias == "test2"
    
    # Get by provider
    keys = await sqlite_backend.get_keys_by_provider("openai")
    assert len(keys) == 1
    
    # Delete
    await sqlite_backend.delete_key(added.id)
    
    # Should be revoked
    fetched = await sqlite_backend.get_key(added.id)
    assert fetched.status == "revoked"

@pytest.mark.asyncio
async def test_sqlite_filters(sqlite_backend):
    k1 = APIKey(provider="openai", key_value="sk-1", alias="prod1", tags=["prod"])
    k2 = APIKey(provider="anthropic", key_value="sk-2", alias="dev1", tags=["dev"])
    
    await sqlite_backend.add_key(k1)
    await sqlite_backend.add_key(k2)
    
    res = await sqlite_backend.get_all_keys(KeyFilter(provider="openai"))
    assert len(res) == 1
    
    res2 = await sqlite_backend.get_all_keys(KeyFilter(tags=["dev"]))
    assert len(res2) == 1
    
    res3 = await sqlite_backend.get_all_keys(KeyFilter(alias_contains="1"))
    assert len(res3) == 2

@pytest.mark.asyncio
async def test_sqlite_usage(sqlite_backend):
    k1 = APIKey(provider="openai", key_value="sk-1")
    await sqlite_backend.add_key(k1)
    
    await sqlite_backend.increment_usage(k1.id, 1, 1, 1)
    fetched = await sqlite_backend.get_key(k1.id)
    assert fetched.daily_usage_count == 1
    
    await sqlite_backend.update_concurrent_usage(k1.id, 1)
    fetched = await sqlite_backend.get_key(k1.id)
    assert fetched.concurrent_usage == 1
    
    # Test resets
    # Fake old last_reset_daily
    old_date = (datetime.now(timezone.utc) - timedelta(days=2)).date()
    # Update directly using the model and backend method since sqlite lock doesn't allow external writes easily
    fetched.last_reset_daily = old_date
    await sqlite_backend.update_key(fetched.id, fetched)
        
    await sqlite_backend.reset_daily_counts(datetime.now(timezone.utc).date())
    fetched = await sqlite_backend.get_key(k1.id)
    assert fetched.daily_usage_count == 0

@pytest.mark.asyncio
async def test_sqlite_bulk(sqlite_backend):
    keys = [
        APIKey(provider="openai", key_value="sk-1"),
        APIKey(provider="openai", key_value="sk-2")
    ]
    res = await sqlite_backend.bulk_add_keys(keys)
    assert res.successful == 2
    
    assert await sqlite_backend.count_keys() == 2
    
    await sqlite_backend.bulk_delete_keys(res.created_ids)
    
    active = await sqlite_backend.count_keys(status="active")
    assert active == 0
