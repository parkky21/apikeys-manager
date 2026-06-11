import pytest
from datetime import datetime, timezone, timedelta
from api_service_handler.storage.memory import MemoryStorageBackend
from api_service_handler.models import APIKey, KeyUpdateRequest, KeyFilter
from api_service_handler.exceptions import KeyNotFoundError, DuplicateKeyError

@pytest.fixture
async def memory_backend():
    backend = MemoryStorageBackend()
    await backend.initialize()
    yield backend
    await backend.close()

@pytest.mark.asyncio
async def test_memory_crud(memory_backend):
    key = APIKey(provider="openai", key_value="sk-test", alias="test1")
    added = await memory_backend.add_key(key)
    
    assert added.id is not None
    
    # Get
    fetched = await memory_backend.get_key(added.id)
    assert fetched.key_value == "sk-test"
    
    # Update
    updated = await memory_backend.update_key(added.id, KeyUpdateRequest(alias="test2"))
    assert updated.alias == "test2"
    
    # Get by provider
    keys = await memory_backend.get_keys_by_provider("openai")
    assert len(keys) == 1
    
    # Delete
    await memory_backend.delete_key(added.id, soft=False)
    with pytest.raises(KeyNotFoundError):
        await memory_backend.get_key(added.id)

@pytest.mark.asyncio
async def test_memory_filters(memory_backend):
    k1 = APIKey(provider="openai", key_value="sk-1", alias="prod1", tags=["prod"])
    k2 = APIKey(provider="anthropic", key_value="sk-2", alias="dev1", tags=["dev"])
    
    await memory_backend.add_key(k1)
    await memory_backend.add_key(k2)
    
    res = await memory_backend.get_all_keys(KeyFilter(provider="openai"))
    assert len(res) == 1
    
    res2 = await memory_backend.get_all_keys(KeyFilter(tags=["dev"]))
    assert len(res2) == 1
    
    res3 = await memory_backend.get_all_keys(KeyFilter(alias_contains="1"))
    assert len(res3) == 2

@pytest.mark.asyncio
async def test_memory_usage(memory_backend):
    k1 = APIKey(provider="openai", key_value="sk-1")
    await memory_backend.add_key(k1)
    
    await memory_backend.increment_usage(k1.id, 1, 1, 1)
    fetched = await memory_backend.get_key(k1.id)
    assert fetched.daily_usage_count == 1
    
    await memory_backend.update_concurrent_usage(k1.id, 1)
    fetched = await memory_backend.get_key(k1.id)
    assert fetched.concurrent_usage == 1

@pytest.mark.asyncio
async def test_memory_bulk(memory_backend):
    keys = [
        APIKey(provider="openai", key_value="sk-1"),
        APIKey(provider="openai", key_value="sk-2")
    ]
    res = await memory_backend.bulk_add_keys(keys)
    assert res.successful == 2
    
    assert await memory_backend.count_keys() == 2
    
    await memory_backend.bulk_delete_keys(res.created_ids)
    
    active = await memory_backend.count_keys(status="active")
    assert active == 0
