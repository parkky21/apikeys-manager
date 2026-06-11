import pytest
from api_service_handler.usage_tracker import UsageTracker
from api_service_handler.storage.memory import MemoryStorageBackend
from api_service_handler.models import APIKey
from api_service_handler.exceptions import MaxConcurrentExceededError

@pytest.fixture
async def usage_tracker():
    backend = MemoryStorageBackend()
    await backend.initialize()
    tracker = UsageTracker(backend)
    yield tracker, backend
    await backend.close()

@pytest.mark.asyncio
async def test_usage_tracker_record(usage_tracker):
    tracker, backend = usage_tracker
    
    key = APIKey(provider="openai", key_value="sk-1")
    await backend.add_key(key)
    
    await tracker.record_usage(key.id, count=2)
    fetched = await backend.get_key(key.id)
    
    assert fetched.daily_usage_count == 2
    assert fetched.total_usage_count == 2
    assert fetched.last_used_at is not None

@pytest.mark.asyncio
async def test_usage_tracker_context(usage_tracker):
    tracker, backend = usage_tracker
    
    key = APIKey(provider="openai", key_value="sk-1", max_concurrent=1)
    await backend.add_key(key)
    
    async with tracker.use(key.id, record=True) as used_key:
        assert used_key.id == key.id
        
        # Check concurrent
        c = await tracker.get_concurrent_usage(key.id)
        assert c == 1
        
        # Max concurrent should fail
        with pytest.raises(MaxConcurrentExceededError):
            async with tracker.use(key.id):
                pass
                
    # Check release
    c = await tracker.get_concurrent_usage(key.id)
    assert c == 0
    
    # Check recorded
    fetched = await backend.get_key(key.id)
    assert fetched.total_usage_count == 1

@pytest.mark.asyncio
async def test_usage_tracker_stats(usage_tracker):
    tracker, backend = usage_tracker
    
    key = APIKey(provider="openai", key_value="sk-1")
    await backend.add_key(key)
    
    stats = await tracker.get_usage_stats(key.id)
    assert stats.key_id == key.id
    assert stats.total_usage_count == 0
    
    all_stats = await tracker.get_provider_stats("openai")
    assert len(all_stats) == 1
    
    await tracker.reset_all_concurrent()
