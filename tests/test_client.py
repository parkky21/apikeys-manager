import pytest
from datetime import datetime, timezone
from api_service_handler.client import APIServiceHandler
from api_service_handler.models import APIKey, KeyCreateRequest, KeyUpdateRequest
from api_service_handler.exceptions import KeyNotFoundError, MaxConcurrentExceededError, NoAvailableKeyError

@pytest.fixture
async def handler():
    client = APIServiceHandler(
        storage_backend="memory",
        auto_reset_counters=True,
        soft_delete=True
    )
    await client.initialize()
    yield client
    await client.close()

@pytest.mark.asyncio
async def test_client_crud(handler):
    key = await handler.add_key(provider="openai", key_value="sk-123", alias="test-key")
    
    assert key.id is not None
    assert key.provider == "openai"
    assert key.alias == "test-key"
    
    fetched = await handler.get_key(key.id)
    assert fetched.id == key.id
    
    # Get by provider
    keys = await handler.get_keys_by_provider("openai")
    assert len(keys) == 1
    
    # Update
    updated = await handler.update_key(key.id, alias="new-alias", daily_limit=10)
    assert updated.alias == "new-alias"
    assert updated.daily_limit == 10
    
    # Delete
    await handler.delete_key(key.id)
    # Since soft delete is true, it should be revoked
    revoked = await handler.get_key(key.id)
    assert revoked.status == "revoked"

@pytest.mark.asyncio
async def test_client_usage(handler):
    key = await handler.add_key(provider="anthropic", key_value="sk-ant", max_concurrent=1)
    
    async with handler.use_key(provider="anthropic") as used_key:
        assert used_key.id == key.id
        
        # Concurrency
        with pytest.raises(NoAvailableKeyError):
            async with handler.use_key(provider="anthropic"):
                pass
                
    # Recorded usage
    fetched = await handler.get_key(key.id)
    assert fetched.total_usage_count == 1
    assert fetched.daily_usage_count == 1

@pytest.mark.asyncio
async def test_client_stats_and_resets(handler):
    key = await handler.add_key(provider="google_gemini", key_value="sk-goog")
    
    # Force some usage directly
    async with handler.use_key(provider="google_gemini"):
        pass
        
    stats = await handler.get_provider_stats("google_gemini")
    assert len(stats) == 1
    assert stats[0].total_usage_count == 1
    
    res = await handler.reset_daily_counts()
    assert res >= 0
    
    res_m = await handler.reset_monthly_counts()
    assert res_m >= 0
    
    stats_after = await handler.get_provider_stats("google_gemini")
    assert stats_after[0].daily_usage_count >= 0

@pytest.mark.asyncio
async def test_client_bulk(handler):
    reqs = [
        KeyCreateRequest(provider="openai", key_value="sk-bulk-1"),
        KeyCreateRequest(provider="openai", key_value="sk-bulk-2")
    ]
    res = await handler.bulk_add_keys(reqs)
    assert res.successful == 2
    
    # Delete them
    del_res = await handler.bulk_delete_keys(res.created_ids)
    assert del_res.successful == 2

@pytest.mark.asyncio
async def test_client_all_properties(handler):
    req = KeyCreateRequest(provider="anthropic", key_value="sk-123", tags=["test"], metadata={"tier": "pro"})
    key = await handler.add_key(provider="anthropic", key_value="sk-123", tags=["test"], metadata={"tier": "pro"})
    
    keys = await handler.get_all_keys(provider="anthropic", tags=["test"])
    assert len(keys) == 1
    
    await handler.record_usage(key.id)
    k2 = await handler.get_key(key.id)
    assert k2.daily_usage_count == 1
