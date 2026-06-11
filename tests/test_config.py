import os
import pytest
from api_service_handler.config import ASHConfig, get_config_from_env

def test_ash_config_defaults():
    config = ASHConfig()
    assert config.storage_backend == "memory"
    assert config.encrypt_keys is True
    assert config.rotation_strategy == "round_robin"
    assert config.auto_reset_counters is True

def test_ash_config_env_fallback(monkeypatch):
    monkeypatch.setenv("ASH_SHARED_SECRET", "env_secret")
    monkeypatch.setenv("ASH_CONNECTION_STRING", "env_conn")
    monkeypatch.setenv("ASH_STORAGE_BACKEND", "sqlite")
    
    config = ASHConfig()
    assert config.shared_secret == "env_secret"
    assert config.connection_string == "env_conn"
    assert config.storage_backend == "sqlite"

def test_get_config_from_env(monkeypatch):
    monkeypatch.setenv("ASH_STORAGE_BACKEND", "mongodb")
    monkeypatch.setenv("ASH_CONNECTION_STRING", "mongodb://localhost")
    monkeypatch.setenv("ASH_SHARED_SECRET", "my_secret")
    monkeypatch.setenv("ASH_ROTATION_STRATEGY", "random")
    monkeypatch.setenv("ASH_ENCRYPT_KEYS", "false")
    monkeypatch.setenv("ASH_AUTO_RESET_COUNTERS", "false")
    monkeypatch.setenv("ASH_SOFT_DELETE", "false")
    monkeypatch.setenv("ASH_DEFAULT_DAILY_LIMIT", "100")
    
    config = get_config_from_env()
    assert config.storage_backend == "mongodb"
    assert config.connection_string == "mongodb://localhost"
    assert config.shared_secret == "my_secret"
    assert config.rotation_strategy == "random"
    assert config.encrypt_keys is False
    assert config.auto_reset_counters is False
    assert config.soft_delete is False
    assert config.default_daily_limit == 100
    assert config.default_monthly_limit is None
