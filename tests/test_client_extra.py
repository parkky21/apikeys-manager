import pytest
from datetime import datetime, timezone, timedelta
from api_service_handler.client import APIServiceHandler
from api_service_handler.models import APIKey, KeyCreateRequest, KeyUpdateRequest
from api_service_handler.exceptions import KeyNotFoundError, MaxConcurrentExceededError

@pytest.fixture
async def handler():
    client = APIServiceHandler(
        storage_backend="memory",
        auto_reset_counters=False,
        soft_delete=False
    )
    await client.initialize()
    yield client
    await client.close()

@pytest.mark.asyncio
async def test_client_extra_methods(handler):
    k1 = await handler.add_key(provider="openai", key_value="sk-ext1", max_concurrent=2, daily_limit=10, monthly_limit=50)
    k2 = await handler.add_key(provider="openai", key_value="sk-ext2", environment="development")
    k3 = await handler.add_key(provider="anthropic", key_value="sk-ant", alias="ant")
    
    # get_all_keys with filters
    keys = await handler.get_all_keys(provider="openai", has_capacity=True)
    assert len(keys) == 2
    
    keys = await handler.get_all_keys(provider="openai", environment="development")
    assert len(keys) == 1
    
    # increment_usage
    await handler.record_usage(k1.id)
    fetched = await handler.get_key(k1.id)
    assert fetched.daily_usage_count == 1
    
    # update_concurrent_usage
    await handler.update_concurrent_usage(k1.id, 1)
    fetched = await handler.get_key(k1.id)
    assert fetched.concurrent_usage == 1
    
    # get_provider_stats
    stats = await handler.get_provider_stats("openai")
    assert len(stats) == 2
    
    # delete_keys_by_provider
    deleted = await handler.delete_keys_by_provider("openai")
    assert deleted == 2
    
    keys_left = await handler.get_all_keys()
    assert len(keys_left) == 1
    
    # bulk_add_keys
    reqs = [
        KeyCreateRequest(provider="google_gemini", key_value="sk-g1"),
        KeyCreateRequest(provider="google_gemini", key_value="sk-g2"),
        KeyCreateRequest(provider="mistral", key_value="sk-m1")
    ]
    res = await handler.bulk_add_keys(reqs)
    assert res.successful == 3
    
    # bulk_update_keys
    upds = {
        res.created_ids[0]: KeyUpdateRequest(alias="g1-alias"),
        res.created_ids[1]: KeyUpdateRequest(daily_limit=5)
    }
    upd_res = await handler.bulk_update_keys(upds)
    assert upd_res.successful == 2
    
    # bulk_delete_keys
    del_res = await handler.bulk_delete_keys(res.created_ids)
    assert del_res.successful == 3

@pytest.mark.asyncio
async def test_client_error_handling(handler):
    with pytest.raises(KeyNotFoundError):
        await handler.get_key("nonexistent")
    
    with pytest.raises(KeyNotFoundError):
        await handler.update_key("nonexistent", alias="foo")
        
    with pytest.raises(KeyNotFoundError):
        await handler.delete_key("nonexistent")

@pytest.mark.asyncio
async def test_client_rotation(handler):
    await handler.add_key(provider="cohere", key_value="sk-1", weight=10)
    await handler.add_key(provider="cohere", key_value="sk-2", weight=1)
    
    async with handler.use_key(provider="cohere") as k:
        assert k.provider == "cohere"
        
    await handler.close()
