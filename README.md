# API Service Handler

A robust, async-first Python package for managing, rate-limiting, rotating, securely storing, and tracking usage of API keys across multiple providers (OpenAI, Anthropic, Google, custom, and many more). Designed for enterprise applications and LLM agent servers that need reliable, high-volume API key management.

---

## Table of Contents
1. [Core Features](#core-features)
2. [Installation](#installation)
3. [Configuration & Initialization](#configuration--initialization)
4. [Storage Backends](#storage-backends)
5. [Managing API Keys](#managing-api-keys)
6. [Using Keys (Rotation & Rate Limiting)](#using-keys-rotation--rate-limiting)
7. [Usage Tracking & Statistics](#usage-tracking--statistics)
8. [CLI Tool (`ash`)](#cli-tool-ash)
9. [Supported Providers](#supported-providers)

---

## Core Features

- **Asynchronous Architecture:** Built natively with `asyncio` for high-throughput, non-blocking applications.
- **Smart Key Rotation:** Automatically distributes API calls using Round Robin, Weighted, Random, or Least Used strategies.
- **Advanced Rate Limiting:** Enforces daily limits, monthly limits, and tracks concurrent active requests to prevent API throttling and unexpected billing overages.
- **Auto-Resetting Counters:** Daily and monthly usage counters automatically reset when the calendar period rolls over.
- **Bank-Grade Encryption:** Protects your API keys at rest using AES-256-GCM encryption.
- **Multiple Storage Backends:** Choose between Memory, SQLite, MongoDB, or PostgreSQL.
- **Extensible Metadata:** Tag keys and attach JSON metadata to query subsets of keys easily (e.g., `environment="production"`, `tags=["tier-1"]`).

---

## Installation

Since the package is currently hosted on GitHub (not PyPI), you can install it using `uv` or `pip` by pointing directly to the repository and specifying a version tag.

Install using `uv` (recommended):

```bash
uv add git+https://github.com/parkky21/apikeys-manager.git@v0.1.0
```

Or using `pip`:

```bash
pip install git+https://github.com/parkky21/apikeys-manager.git@v0.1.0
```

### Optional Database Dependencies
If you plan to use **MongoDB** or **PostgreSQL** as your storage backend, install the relevant extras:

```bash
# For MongoDB support
uv add "git+https://github.com/parkky21/apikeys-manager.git@v0.1.0#egg=api-service-handler[mongodb]"

# For PostgreSQL support
uv add "git+https://github.com/parkky21/apikeys-manager.git@v0.1.0#egg=api-service-handler[postgresql]"
```

---

## Configuration & Initialization

The main entry point to the library is the `APIServiceHandler` class. It manages the connection to your underlying database, loads the encryption settings, and serves as the facade for all operations.

### Programmatic Setup

```python
import asyncio
from api_service_handler.client import APIServiceHandler

async def main():
    handler = APIServiceHandler(
        storage_backend="sqlite",                   # memory, sqlite, mongodb, postgresql
        connection_string="sqlite:///api_keys.db",  # Path or URI to database
        encrypt_keys=True,                          # Strongly recommended
        shared_secret="your-super-secret-32-byte-key-here!!!", # Used for AES-GCM encryption
        rotation_strategy="round_robin",            # round_robin, least_used, random, weighted
        auto_reset_counters=True,                   # Auto-refresh quotas on day/month rollover
        soft_delete=True                            # Keep deleted keys as "revoked" for auditing
    )
    
    # You MUST initialize the handler to establish db connections/pools
    await handler.initialize()
    
    print("API Service Handler is ready!")
    
    # Safely close connections before your app shuts down
    await handler.close()

if __name__ == "__main__":
    asyncio.run(main())
```

### Environment Variables
You can configure the client purely using environment variables. If you omit parameters when instantiating `APIServiceHandler()`, it falls back to these:

- `ASH_STORAGE_BACKEND`: `memory`, `sqlite`, `mongodb`, or `postgresql`
- `ASH_CONNECTION_STRING`: Database URI
- `ASH_SHARED_SECRET`: Secret key for AES encryption
- `ASH_ROTATION_STRATEGY`: Default rotation strategy

---

## Storage Backends

1. **Memory (`memory`)**: Ideal for ephemeral testing and scripts. Data is lost on restart. No connection string required.
2. **SQLite (`sqlite`)**: Great for local servers. `connection_string` should be `sqlite:///path/to/db.sqlite` or `sqlite:///:memory:`.
3. **MongoDB (`mongodb`)**: Requires the `[mongodb]` extra (motor). Uses standard MongoDB URIs: `mongodb://user:pass@localhost:27017/dbname`.
4. **PostgreSQL (`postgresql`)**: Requires the `[postgresql]` extra (asyncpg). Uses standard PostgreSQL URIs: `postgresql://user:pass@localhost:5432/dbname`.

---

## Managing API Keys

### Adding a Key
Keys can be added one by one, or in bulk.

```python
from api_service_handler.models import Environment

key = await handler.add_key(
    provider="openai",               # Supported provider enum string
    key_value="sk-proj-1234567890",  # The raw API key
    alias="prod-gpt4-key",           # Friendly name
    daily_limit=1000,                # Max 1000 uses per day
    monthly_limit=25000,             # Max 25000 uses per month
    max_concurrent=5,                # Max 5 active parallel requests
    environment=Environment.PRODUCTION,
    tags=["premium", "gpt-4"],
    metadata={"billing_account": "acct_123"},
    weight=10                        # Useful if using "weighted" rotation
)
```

### Retrieving Keys
Keys are retrieved as `APIKey` Pydantic models. By default, `key_value` is encrypted at rest and will remain encrypted or masked unless you explicitly ask to decrypt it.

```python
# Get a specific key
key = await handler.get_key(key_id="uuid-string", decrypt=True)
print(key.key_value) # sk-proj-1234...

# Get all keys for a provider
anthropic_keys = await handler.get_keys_by_provider("anthropic")

# Complex Filtering
filtered_keys = await handler.get_all_keys(
    provider="google_gemini",
    tags=["premium"],
    environment="production",
    has_capacity=True # Only returns keys that haven't hit rate/concurrency limits!
)
```

### Updating & Deleting
```python
# Update a key's alias and limit
updated = await handler.update_key(
    key.id, 
    alias="new-alias", 
    daily_limit=2000
)

# Soft delete (marks as revoked)
await handler.delete_key(key.id, hard=False)

# Hard delete (completely removes from DB)
await handler.delete_key(key.id, hard=True)
```

---

## Using Keys (Rotation & Rate Limiting)

The core purpose of this library is to safely dispense API keys while preventing you from hitting provider rate limits. 

The **safest and easiest** way to retrieve a key is using the `use_key` context manager. It will:
1. Find an active key for the requested provider.
2. Filter out keys that have hit their Daily/Monthly limits.
3. Filter out keys that have hit their Max Concurrent usage limit.
4. Rotate between the valid keys based on your strategy (e.g. Round Robin).
5. Increment the concurrent usage counter.
6. Once the `async with` block exits, it decrements the concurrent counter and increments the total/daily/monthly usage counts.

```python
from api_service_handler.exceptions import RateLimitExceededError, NoAvailableKeyError, MaxConcurrentExceededError

async def generate_text(prompt: str):
    try:
        # Request a key for Anthropic that is designated for production
        async with handler.use_key(provider="anthropic", environment="production") as api_key:
            
            # The key is automatically decrypted and ready to use
            raw_key = api_key.key_value
            
            # Pass the raw_key into your SDK of choice
            # response = await my_llm_client.chat(api_key=raw_key, messages=prompt)
            print(f"Executing request with {api_key.alias}")
            
    except NoAvailableKeyError:
        print("No active Anthropic keys found!")
    except RateLimitExceededError as e:
        print(f"All keys are rate limited! {e}")
    except MaxConcurrentExceededError as e:
        print(f"Too many parallel requests active right now! {e}")
```

---

## Usage Tracking & Statistics

Track exactly how much your APIs are being utilized. Counters auto-reset at the start of a new calendar day/month based on UTC time.

```python
# Get usage for a specific key
stats = await handler.get_usage_stats(key.id)
print(f"Daily remaining: {stats.daily_remaining}")
print(f"Total historical uses: {stats.total_usage_count}")

# Get aggregated usage across all keys for a provider
provider_stats = await handler.get_provider_stats("openai")
for stat in provider_stats:
    print(f"{stat.alias}: {stat.daily_usage_count} uses today")

# Manually force a reset of daily counters across all keys
reset_count = await handler.reset_daily_counts()
print(f"Reset daily limits for {reset_count} keys.")
```

---

## CLI Tool (`ash`)

A full-featured command-line utility is bundled with the package for administrative tasks.

Ensure you have your environment variables exported so the CLI connects to your production database:
```bash
export ASH_STORAGE_BACKEND="postgresql"
export ASH_CONNECTION_STRING="postgresql://user:pass@localhost/db"
export ASH_SHARED_SECRET="my-super-secret-key"
```

### CLI Commands

**Adding a Key**
```bash
ash keys add --provider openai --key "sk-proj-xyz" --alias "prod-1" --daily-limit 5000
```

**Listing Keys**
```bash
ash keys list
ash keys list --json
ash keys list --provider anthropic --show-keys
```

**Viewing Key Info**
```bash
ash keys get <key_id>
```

**Updating & Deleting**
```bash
ash keys update <key_id> --alias "new-name" --status inactive
ash keys delete <key_id> --hard
```

**Usage & Diagnostics**
```bash
ash usage stats <key_id>
ash usage reset-daily
ash health
ash info
```

---

## Supported Providers

The library enforces strict string enums for API providers. When providing the `provider` string, you can use any of the following (case-insensitive):

- **AI / LLM:** `openai`, `anthropic`, `google_gemini`, `google_vertex`, `mistral`, `cohere`, `huggingface`, `replicate`, `together_ai`, `groq`, `fireworks`, `deepseek`, `xai`, `perplexity`, `openrouter`
- **Speech / Audio:** `deepgram`, `eleven_labs`, `assembly_ai`, `whisper`
- **Cloud & Auth:** `aws`, `azure`, `gcp`, `cloudflare`, `vercel`, `auth0`, `clerk`, `supabase_auth`
- **Communication:** `twilio`, `sendgrid`, `mailgun`, `resend`, `postmark`
- **Payments:** `stripe`, `razorpay`, `paypal`, `lemonsqueezy`
- **Search & Vector:** `serp_api`, `bing_search`, `algolia`, `pinecone`, `weaviate`
- **Misc:** `github`, `slack`, `discord`, `custom`

*(If a provider isn't strictly typed, it will safely fallback to `"custom"`, though you can also just pass `"custom"`).*
