import asyncio
import os
import tempfile
from collections.abc import AsyncGenerator, Generator

import pytest
import pytest_asyncio

from api_service_handler.client import APIServiceHandler
from api_service_handler.config import ASHConfig

@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create an instance of the default event loop for each test case."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest_asyncio.fixture
async def memory_handler() -> AsyncGenerator[APIServiceHandler, None]:
    handler = APIServiceHandler(
        storage_backend="memory",
        shared_secret="test_secret_for_encryption_tests"
    )
    await handler.initialize()
    yield handler
    await handler.close()

@pytest_asyncio.fixture
async def unencrypted_memory_handler() -> AsyncGenerator[APIServiceHandler, None]:
    handler = APIServiceHandler(
        storage_backend="memory",
        encrypt_keys=False
    )
    await handler.initialize()
    yield handler
    await handler.close()

@pytest_asyncio.fixture
async def sqlite_handler() -> AsyncGenerator[APIServiceHandler, None]:
    # Use an in-memory SQLite DB or a temp file
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    
    handler = APIServiceHandler(
        storage_backend="sqlite",
        connection_string=f"sqlite:///{db_path}",
        shared_secret="test_secret_for_encryption_tests"
    )
    await handler.initialize()
    yield handler
    await handler.close()
    
    # Cleanup
    if os.path.exists(db_path):
        os.remove(db_path)
