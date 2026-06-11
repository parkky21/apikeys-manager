import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from api_service_handler.storage.postgresql import PostgreSQLStorageBackend
from api_service_handler.models import APIKey

@pytest.mark.asyncio
@patch('api_service_handler.storage.postgresql._try_import_asyncpg')
async def test_postgresql_backend_mocked(mock_asyncpg_import):
    mock_asyncpg = AsyncMock()
    mock_asyncpg_import.return_value = mock_asyncpg
    
    mock_pool = MagicMock()
    mock_pool.close = AsyncMock()
    mock_asyncpg.create_pool.return_value = mock_pool
    
    # Setup conn acquired from pool
    mock_conn = AsyncMock()
    mock_conn_ctx = MagicMock()
    mock_conn_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn_ctx.__aexit__ = AsyncMock(return_value=None)
    mock_pool.acquire.return_value = mock_conn_ctx
    
    backend = PostgreSQLStorageBackend("postgresql://localhost")
    await backend.initialize()
    
    assert mock_asyncpg.create_pool.called
    assert mock_conn.execute.called # For table creation
    
    # Test Add Key
    key = APIKey(provider="openai", key_value="sk-test")
    await backend.add_key(key)
    assert mock_conn.execute.called
    
    # Test Get Key
    mock_conn.fetchrow.return_value = {"id": key.id, "provider": "openai", "key_value": "sk-test", "status": "active", "environment": "production"}
    fetched = await backend.get_key(key.id)
    assert fetched.id == key.id
    
    # Test Update Key
    await backend.update_key(key.id, MagicMock(model_dump=lambda exclude_unset: {"alias": "new"}))
    assert mock_conn.execute.called
    
    # Test Health Check
    assert await backend.health_check() is True
    
    await backend.close()
    assert mock_pool.close.called
