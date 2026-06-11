# API Service Handler

A robust, async-first Python package for managing, rate-limiting, rotating, and tracking usage of API keys across multiple providers (OpenAI, Anthropic, Google, and many more).

## Features

- **Multi-Provider Support:** Manage keys for AI models, payment gateways, cloud services, and more.
- **Async First:** Built entirely on asynchronous I/O (`asyncio`).
- **Flexible Storage:** Works out of the box with Memory and SQLite. Easily extendable to MongoDB and PostgreSQL.
- **Intelligent Rotation:** Supports Round Robin, Weighted, Random, and Least Used key rotation strategies.
- **Rate Limiting:** Enforce daily, monthly, and concurrent usage limits to prevent runaway costs.
- **Encryption at Rest:** Keys are securely stored using AES-256-GCM encryption.
- **CLI Utility:** Comes with the `ash` command-line tool for easy human-friendly key management.

## Installation

Install using `uv` (recommended):

```bash
uv add api-service-handler
```

Or using `pip`:

```bash
pip install api-service-handler
```

### Optional Dependencies
If you plan to use MongoDB or PostgreSQL as your storage backend, install the relevant extras:

```bash
# For MongoDB support
uv add "api-service-handler[mongodb]"

# For PostgreSQL support
uv add "api-service-handler[postgresql]"
```

## Quick Start

### 1. Initialization

Initialize the `APIServiceHandler` client. By default, it runs an in-memory storage backend.

```python
import asyncio
from api_service_handler.client import APIServiceHandler

async def main():
    # Initialize the client (SQLite example)
    handler = APIServiceHandler(
        storage_backend="sqlite",
        connection_string="sqlite:///api_keys.db",
        encrypt_keys=True,
        shared_secret="your-super-secret-encryption-key-32c!"
    )
    
    await handler.initialize()
    
    # Do work here...
    
    # Close connections when shutting down
    await handler.close()

if __name__ == "__main__":
    asyncio.run(main())
```

### 2. Adding Keys

```python
# Add an OpenAI key with rate limits
key = await handler.add_key(
    provider="openai",
    key_value="sk-1234567890",
    alias="prod-openai-1",
    daily_limit=1000,
    monthly_limit=50000,
    max_concurrent=5
)

print(f"Added key {key.id} for {key.provider}")
```

### 3. Using Keys (With Rotation & Rate Limiting)

The recommended way to access keys is via the asynchronous `use_key` context manager. It automatically handles key rotation, checks limits, prevents concurrency bottlenecks, and tracks usage counters behind the scenes.

```python
async def generate_text():
    # Fetches an available key for Anthropic. 
    # If multiple exist, it rotates based on the chosen strategy (default: Round Robin).
    async with handler.use_key(provider="anthropic") as api_key:
        print(f"Using key: {api_key.key_value}")
        
        # Make your actual API request here
        # ...
```

### 4. Viewing Usage Statistics

You can easily query how much an API has been used.

```python
stats = await handler.get_usage_stats(key.id)
print(f"Daily usage: {stats.daily_usage_count}/{stats.daily_limit}")
```

## CLI Usage

The package bundles a powerful CLI tool named `ash`.

```bash
# Add a new key
ash keys add --provider openai --key sk-yourkey --alias prod-1 --daily-limit 500

# List all stored keys
ash keys list

# View stats for a specific key
ash usage stats <key_id>
```

By default, the CLI uses a local `.ash.db` SQLite database. You can customize the storage by exporting environment variables:

```bash
export ASH_STORAGE_BACKEND="postgresql"
export ASH_CONNECTION_STRING="postgresql://user:pass@localhost:5432/db"
export ASH_SHARED_SECRET="my-encryption-key"

ash keys list
```

## Testing

This project maintains high test coverage (>90%). To run tests locally:

```bash
uv run pytest --cov=api_service_handler
```
