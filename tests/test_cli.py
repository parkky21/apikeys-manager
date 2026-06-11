import os
import json
import tempfile
import pytest
from click.testing import CliRunner
from api_service_handler.cli import cli
from api_service_handler.enums import Provider

@pytest.fixture
def runner(monkeypatch):
    # Use sqlite so data persists across invocations
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(db_fd)
    
    monkeypatch.setenv("ASH_STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("ASH_CONNECTION_STRING", f"sqlite:///{db_path}")
    
    yield CliRunner()
    
    if os.path.exists(db_path):
        os.unlink(db_path)

def test_cli_health(runner):
    result = runner.invoke(cli, ['health'])
    assert result.exit_code == 0
    assert "Storage backend is healthy!" in result.output or "Storage backend is NOT healthy!" in result.output

def test_cli_info(runner):
    result = runner.invoke(cli, ['info'])
    assert result.exit_code == 0
    assert "API Service Handler Info" in result.output
    assert "total_keys:" in result.output

def test_cli_keys_add_and_list(runner):
    # Add a key
    add_result = runner.invoke(cli, ['keys', 'add', '--provider', 'openai', '--key', 'sk-testcli'])
    assert add_result.exit_code == 0
    assert "Successfully added key!" in add_result.output
    
    # List keys
    list_result = runner.invoke(cli, ['keys', 'list'])
    assert list_result.exit_code == 0
    assert "openai" in list_result.output
    
    # List keys json
    list_json_result = runner.invoke(cli, ['keys', 'list', '--json'])
    assert list_json_result.exit_code == 0
    data = json.loads(list_json_result.output)
    assert len(data) >= 1
    assert data[0]["provider"] == "openai"
    
    key_id = data[0]["id"]
    
    # Get
    info_res = runner.invoke(cli, ['keys', 'get', key_id])
    assert info_res.exit_code == 0
    
    # Update
    upd_res = runner.invoke(cli, ['keys', 'update', key_id, '--alias', 'new-alias'])
    assert upd_res.exit_code == 0
    
    # Delete
    del_res = runner.invoke(cli, ['keys', 'delete', key_id, '--hard'])
    assert del_res.exit_code == 0

def test_cli_usage_extended(runner):
    runner.invoke(cli, ['keys', 'add', '--provider', 'openai', '--key', 'sk-usage'])
    list_res = runner.invoke(cli, ['keys', 'list', '--json'])
    data = json.loads(list_res.output)
    key_id = data[0]["id"]
    
    # Stats
    stats_res = runner.invoke(cli, ['usage', 'stats', key_id])
    assert stats_res.exit_code == 0

def test_cli_usage_stats_and_resets(runner):
    add_result = runner.invoke(cli, ['keys', 'add', '--provider', 'anthropic', '--key', 'sk-testcli2'])
    assert add_result.exit_code == 0
    
    # We can't easily extract ID from output without parsing, let's just test the reset commands
    reset_daily = runner.invoke(cli, ['usage', 'reset-daily'])
    assert reset_daily.exit_code == 0
    assert "Reset daily counters for" in reset_daily.output
    
    reset_monthly = runner.invoke(cli, ['usage', 'reset-monthly'])
    assert reset_monthly.exit_code == 0
    assert "Reset monthly counters for" in reset_monthly.output
