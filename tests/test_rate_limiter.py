import pytest
from datetime import datetime, timezone, timedelta
from api_service_handler.rate_limiter import RateLimiter
from api_service_handler.storage.memory import MemoryStorageBackend
from api_service_handler.models import APIKey, KeyUpdateRequest
from api_service_handler.exceptions import RateLimitExceededError

@pytest.fixture
async def rate_limiter():
    backend = MemoryStorageBackend()
    await backend.initialize()
    limiter = RateLimiter(backend, auto_reset=True)
    yield limiter, backend
    await backend.close()

@pytest.mark.asyncio
async def test_rate_limiter_check_and_update(rate_limiter):
    limiter, backend = rate_limiter
    
    key = APIKey(
        provider="openai",
        key_value="sk-1",
        daily_limit=2,
        monthly_limit=5
    )
    await backend.add_key(key)
    
    # Should pass
    await limiter.enforce_limits(key)
    
    # Fake usage
    await backend.increment_usage(key.id, daily=2)
    key = await backend.get_key(key.id)
    
    with pytest.raises(RateLimitExceededError):
        await limiter.enforce_limits(key)
        
    # Auto reset test
    old_date = datetime.now(timezone.utc).date() - timedelta(days=1)
    key.last_reset_daily = old_date
    await backend.update_key(key.id, KeyUpdateRequest(expires_at=None)) # any update
    
    # We must patch the key manually since memory backend doesn't support direct object modification sync
    fetched_key = await backend.get_key(key.id)
    fetched_key.last_reset_daily = old_date
    await backend.delete_key(fetched_key.id, soft=False)
    await backend.add_key(fetched_key)
    
    updated_key = await limiter.check_and_update(fetched_key)
    assert updated_key.daily_usage_count == 0
    assert updated_key.last_reset_daily > old_date
    
@pytest.mark.asyncio
async def test_rate_limiter_resets(rate_limiter):
    limiter, backend = rate_limiter
    
    key = APIKey(provider="openai", key_value="sk-1", daily_usage_count=10)
    key.last_reset_daily = datetime.now(timezone.utc).date() - timedelta(days=2)
    key.last_reset_monthly = (datetime.now(timezone.utc) - timedelta(days=40)).date()
    
    await backend.add_key(key)
    
    await limiter.reset_daily()
    fetched = await backend.get_key(key.id)
    assert fetched.daily_usage_count == 0
    
    await limiter.reset_monthly()
    fetched = await backend.get_key(key.id)
    assert fetched.monthly_usage_count == 0
