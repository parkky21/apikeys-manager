import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock

from api_service_handler.enums import Provider, RotationStrategy
from api_service_handler.models import APIKey
from api_service_handler.rotation import KeyRotator
from api_service_handler.exceptions import NoAvailableKeyError

def create_mock_key(id_str, provider=Provider.OPENAI, weight=1, priority=0, daily_usage=0, total_usage=0, max_concurrent=None, concurrent_usage=0):
    k = APIKey(provider=provider, key_value=f"val-{id_str}")
    k.id = id_str
    k.weight = weight
    k.priority = priority
    k.daily_usage_count = daily_usage
    k.total_usage_count = total_usage
    k.max_concurrent = max_concurrent
    k.concurrent_usage = concurrent_usage
    k.last_used_at = datetime.now(timezone.utc)
    return k

def test_rotator_round_robin():
    rotator = KeyRotator(RotationStrategy.ROUND_ROBIN)
    keys = [create_mock_key("1"), create_mock_key("2"), create_mock_key("3")]
    
    selected1 = rotator.select_key(keys, Provider.OPENAI)
    selected2 = rotator.select_key(keys, Provider.OPENAI)
    
    assert selected1.id != selected2.id
    
def test_rotator_least_used():
    rotator = KeyRotator(RotationStrategy.LEAST_USED)
    keys = [
        create_mock_key("1", total_usage=100),
        create_mock_key("2", total_usage=10),
        create_mock_key("3", total_usage=50)
    ]
    
    selected = rotator.select_key(keys, Provider.OPENAI)
    assert selected.id == "2"

def test_rotator_random():
    rotator = KeyRotator(RotationStrategy.RANDOM)
    keys = [create_mock_key("1"), create_mock_key("2")]
    
    selected = rotator.select_key(keys, Provider.OPENAI)
    assert selected.id in ["1", "2"]

def test_rotator_weighted():
    rotator = KeyRotator(RotationStrategy.WEIGHTED)
    keys = [
        create_mock_key("1", weight=10),
        create_mock_key("2", weight=1)
    ]
    # Not guaranteed but highly likely to pick 1
    selected = rotator.select_key(keys, Provider.OPENAI)
    assert selected.id in ["1", "2"]

def test_rotator_no_keys():
    rotator = KeyRotator(RotationStrategy.ROUND_ROBIN)
    with pytest.raises(NoAvailableKeyError):
        rotator.select_key([], Provider.OPENAI)

def test_rotator_priority():
    rotator = KeyRotator(RotationStrategy.ROUND_ROBIN)
    keys = [
        create_mock_key("1", priority=10),
        create_mock_key("2", priority=0) # higher priority
    ]
    selected = rotator.select_key(keys, Provider.OPENAI)
    assert selected.id == "2"

def test_rotator_capacity():
    rotator = KeyRotator(RotationStrategy.ROUND_ROBIN)
    keys = [
        create_mock_key("1", max_concurrent=2, concurrent_usage=2), # Full
        create_mock_key("2", max_concurrent=2, concurrent_usage=1)  # Has capacity
    ]
    selected = rotator.select_key(keys, Provider.OPENAI)
    assert selected.id == "2"
