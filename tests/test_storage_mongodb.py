import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from api_service_handler.storage.mongodb import MongoDBStorageBackend
from api_service_handler.models import APIKey

@pytest.mark.asyncio
@patch('api_service_handler.storage.mongodb._try_import_motor')
async def test_mongodb_backend_mocked(mock_motor_import):
    # Setup mocks
    mock_motor = MagicMock()
    mock_motor_import.return_value = mock_motor
    
    mock_client = MagicMock()
    mock_motor.AsyncIOMotorClient.return_value = mock_client
    
    mock_db = MagicMock()
    mock_client.__getitem__.return_value = mock_db
    mock_client.get_database.return_value.name = "test_db"
    
    mock_collection = AsyncMock()
    mock_db.__getitem__.return_value = mock_collection
    
    # Initialize backend
    backend = MongoDBStorageBackend("mongodb://localhost")
    await backend.initialize()
    
    # Test Add Key
    key = APIKey(provider="openai", key_value="sk-test")
    await backend.add_key(key)
    assert mock_collection.insert_one.called
    
    # Test Get Key
    mock_collection.find_one.return_value = {"_id": key.id, "provider": "openai", "key_value": "sk-test", "status": "active", "environment": "production"}
    fetched = await backend.get_key(key.id)
    assert fetched.id == key.id
    assert fetched.provider == "openai"
    
    # Test Update Key
    await backend.update_key(key.id, MagicMock(model_dump=lambda exclude_unset: {"alias": "new"}))
    assert mock_collection.update_one.called
    
    # Test Delete Key
    await backend.delete_key(key.id, soft=True)
    assert mock_collection.update_one.called
    
    # Test Health Check
    mock_client.admin.command = AsyncMock(return_value={"ok": 1})
    assert await backend.health_check() is True
    
    # Close
    await backend.close()
    assert mock_client.close.called
