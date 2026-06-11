import pytest
from datetime import datetime, timezone, timedelta
from api_service_handler.models import APIKey, KeyFilter, KeyCreateRequest, KeyUpdateRequest
from api_service_handler.enums import Provider, KeyStatus, Environment

def test_api_key_properties():
    now = datetime.now(timezone.utc)
    
    key = APIKey(
        provider=Provider.OPENAI,
        key_value="sk-123",
        daily_limit=10,
        monthly_limit=100,
        max_concurrent=5,
        daily_usage_count=10, # at limit
        expires_at=now - timedelta(days=1) # expired
    )
    
    assert key.is_expired is True
    assert key.is_rate_limited is True
    assert key.has_capacity is False

    key2 = APIKey(
        provider=Provider.OPENAI,
        key_value="sk-123",
        daily_limit=10,
        monthly_limit=100,
        max_concurrent=5,
        daily_usage_count=5, # not at limit
        concurrent_usage=5, # at max concurrent
        status=KeyStatus.ACTIVE
    )
    assert key2.is_expired is False
    assert key2.is_rate_limited is False
    assert key2.has_capacity is False # because concurrent_usage == max_concurrent

def test_key_filter():
    key = APIKey(
        provider=Provider.ANTHROPIC,
        key_value="sk-123",
        status=KeyStatus.ACTIVE,
        environment=Environment.PRODUCTION,
        tags=["premium", "test"],
        metadata={"tier": "pro"},
        alias="test-alias"
    )
    
    f1 = KeyFilter(provider=Provider.ANTHROPIC)
    assert f1.matches(key) is True
    
    f2 = KeyFilter(provider=Provider.OPENAI)
    assert f2.matches(key) is False
    
    f3 = KeyFilter(tags=["premium"])
    assert f3.matches(key) is True
    
    f4 = KeyFilter(tags=["free"])
    assert f4.matches(key) is False
    
    f5 = KeyFilter(metadata_filter={"tier": "pro"})
    assert f5.matches(key) is True
    
    f6 = KeyFilter(alias_contains="alias")
    assert f6.matches(key) is True

def test_key_requests():
    req = KeyCreateRequest(provider="openai", key_value="sk-1")
    assert req.provider == Provider.OPENAI
    
    upd = KeyUpdateRequest(alias="new-alias")
    assert upd.alias == "new-alias"
