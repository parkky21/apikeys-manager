<div align="center">
  <h1>🚀 API Service Handler</h1>
  <p><b>Enterprise-grade, async-first API key management for modern AI applications.</b></p>
  
  <p>
    <img src="https://img.shields.io/badge/python-3.10%2B-blue.svg" alt="Python Version" />
    <img src="https://img.shields.io/badge/coverage-90%25-brightgreen.svg" alt="Test Coverage" />
    <img src="https://img.shields.io/badge/asyncio-native-blueviolet.svg" alt="Asyncio" />
    <img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License" />
  </p>
</div>

<br/>

A robust, async-first Python package for managing, rate-limiting, rotating, securely storing, and tracking usage of API keys across multiple providers (OpenAI, Anthropic, Google, and many more). Designed for LLM agent servers that need reliable, high-volume API key management.

---

## ✨ Core Features

| Feature | Description |
| --- | --- |
| ⚡ **Async Native** | Built entirely with `asyncio` for high-throughput, non-blocking applications. |
| 🔄 **Smart Rotation** | Automatically distributes API calls using Round Robin, Weighted, Random, or Least Used strategies. |
| 🛡️ **Rate Limiting** | Enforces daily, monthly, and concurrent usage limits to prevent throttling and unexpected billing overages. |
| 🔐 **Bank-Grade Encryption** | Protects your API keys at rest using AES-256-GCM encryption. |
| 🗄️ **Flexible Storage** | Choose between Memory, SQLite, MongoDB, or PostgreSQL backends out of the box. |
| 🏷️ **Extensible Metadata** | Tag keys and attach JSON metadata to easily query subsets of keys (e.g., `environment="prod"`). |

---

## 📦 Installation

Since the package is currently hosted on GitHub, you can install it using `uv` or `pip` by pointing directly to the repository and specifying a version tag.

> [!TIP]
> **Recommended:** Install using `uv` for lightning-fast dependency resolution.

```bash
uv add git+https://github.com/parkky21/apikeys-manager.git@v0.1.4
```

*Or using pip:*
```bash
pip install git+https://github.com/parkky21/apikeys-manager.git@v0.1.4
```

<details>
<summary><b>🗄️ Database Specific Extras (Click to expand)</b></summary>

If you plan to use **MongoDB** or **PostgreSQL** as your storage backend, install the relevant extras:

```bash
# For MongoDB support
uv add "git+https://github.com/parkky21/apikeys-manager.git@v0.1.4#egg=api-service-handler[mongodb]"

# For PostgreSQL support
uv add "git+https://github.com/parkky21/apikeys-manager.git@v0.1.4#egg=api-service-handler[postgresql]"
```

</details>

---

## ⚙️ Configuration & Initialization

The main entry point to the library is the `APIServiceHandler` class. It manages the connection to your underlying database, loads the encryption settings, and serves as the facade for all operations.

```python
import asyncio
from api_service_handler.client import APIServiceHandler

async def main():
    handler = APIServiceHandler(
        storage_backend="sqlite",                   # memory, sqlite, mongodb, postgresql
        connection_string="sqlite:///api_keys.db",  # Path or URI to database
        encrypt_keys=True,                          # Strongly recommended
        shared_secret="your-super-secret-32-byte-key-here!!!", # Used for AES-GCM
        rotation_strategy="round_robin",            # round_robin, least_used, random, weighted
        auto_reset_counters=True,                   # Auto-refresh quotas on day/month rollover
        soft_delete=True                            # Keep deleted keys as "revoked" for auditing
    )
    
    # ⚠️ You MUST initialize the handler to establish db connections
    await handler.initialize()
    
    print("🚀 API Service Handler is ready!")
    
    # Safely close connections before your app shuts down
    await handler.close()

if __name__ == "__main__":
    asyncio.run(main())
```

> [!NOTE]
> **Environment Variables:** You can configure the client purely using environment variables (`ASH_STORAGE_BACKEND`, `ASH_CONNECTION_STRING`, `ASH_SHARED_SECRET`, `ASH_ROTATION_STRATEGY`).

---

## 🔑 Managing API Keys

### Adding a Key
Add keys dynamically with precise controls over their environments and usage thresholds.

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

### Retrieving & Filtering
Keys are retrieved as `APIKey` Pydantic models. **By default, `key_value` is encrypted at rest and will remain masked unless explicitly requested.**

```python
# Get a specific key (Decrypted)
key = await handler.get_key(key_id="uuid-string", decrypt=True)

# Complex Filtering
filtered_keys = await handler.get_all_keys(
    provider="google_gemini",
    tags=["premium"],
    environment="production",
    has_capacity=True # ✨ Magic! Only returns keys that haven't hit rate limits
)
```

### 🎯 Metadata Filtering (Deep Search)
You can attach arbitrary JSON metadata to any key and query against it. All storage backends (including Memory & SQLite) natively support filtering by nested metadata using dot-notation!

```python
# Returns only keys assigned to the engineering team
engineering_keys = await handler.get_all_keys(
    metadata_filter={"team": "engineering"}
)

# Nested JSON matching using dot-notation!
enterprise_keys = await handler.get_all_keys(
    metadata_filter={"billing.tier": "enterprise"}
)

# You can even route requests strictly based on metadata!
async with handler.use_key(provider="openai", metadata_filter={"project_id": "proj-789"}) as p_key:
    pass
```

---

## ♻️ Using Keys (Rotation & Rate Limiting)

The core purpose of this library is to safely dispense API keys while preventing you from hitting provider rate limits. 

The **safest and easiest** way to retrieve a key is using the `use_key` context manager. It automatically:
1. Filters out keys that have hit their Daily/Monthly limits.
2. Filters out keys that have hit their Max Concurrent limit.
3. Rotates between valid keys based on your strategy.
4. Safely tracks parallel execution blocks and historical usage.

```python
from api_service_handler.exceptions import RateLimitExceededError, NoAvailableKeyError, MaxConcurrentExceededError

async def generate_text(prompt: str):
    try:
        # Request a key for Anthropic that is designated for production
        async with handler.use_key(provider="anthropic", environment="production") as api_key:
            
            # The key is automatically decrypted and ready to use
            raw_key = api_key.key_value
            print(f"Executing request with {api_key.alias}")
            
            # response = await my_llm_client.chat(api_key=raw_key, messages=prompt)
            
    except NoAvailableKeyError:
        print("❌ No active Anthropic keys found!")
    except RateLimitExceededError as e:
        print(f"🛑 All keys are rate limited! {e}")
    except MaxConcurrentExceededError as e:
        print(f"⚠️ Too many parallel requests active right now! {e}")
```

---

## 📊 Usage Tracking & Statistics

Track exactly how much your APIs are being utilized. Counters auto-reset at the start of a new calendar day/month based on UTC time.

```python
# Get usage for a specific key
stats = await handler.get_usage_stats(key.id)
print(f"Daily remaining: {stats.daily_remaining}")

# Get aggregated usage across all keys for a provider
provider_stats = await handler.get_provider_stats("openai")
for stat in provider_stats:
    print(f"{stat.alias}: {stat.daily_usage_count} uses today")
```

---

## 💻 CLI Tool (`ash`)

A full-featured command-line utility is bundled with the package for administrative tasks.

> [!IMPORTANT]
> Ensure you have your environment variables exported so the CLI connects to your production database!
> `export ASH_CONNECTION_STRING="postgresql://user:pass@localhost/db"`

| Command | Description | Example |
| :--- | :--- | :--- |
| `ash keys add` | Add a new key | `ash keys add --provider openai --key "sk-xyz" --alias "prod"` |
| `ash keys list` | List all keys visually | `ash keys list --provider anthropic --show-keys` |
| `ash keys get` | View detailed key info | `ash keys get <key_id>` |
| `ash keys update`| Update aliases or limits | `ash keys update <key_id> --alias "new-name"` |
| `ash keys delete`| Soft/Hard delete a key | `ash keys delete <key_id> --hard` |
| `ash usage stats`| View limit vs usage data | `ash usage stats <key_id>` |
| `ash health` | Test DB connection | `ash health` |

---

## 🌐 Supported Providers

The library enforces strict string enums for API providers. You can use any of the following (case-insensitive):

<details open>
<summary><b>Click to see full list</b></summary>

- **🤖 AI / LLM:** `openai`, `anthropic`, `google_gemini`, `google_vertex`, `mistral`, `cohere`, `huggingface`, `replicate`, `together_ai`, `groq`, `fireworks`, `deepseek`, `xai`, `perplexity`, `openrouter`, `lemofox`
- **🎙️ Speech / Audio:** `deepgram`, `eleven_labs`, `assembly_ai`, `whisper`
- **☁️ Cloud & Auth:** `aws`, `azure`, `gcp`, `cloudflare`, `vercel`, `auth0`, `clerk`, `supabase_auth`
- **💬 Communication:** `twilio`, `sendgrid`, `mailgun`, `resend`, `postmark`
- **💳 Payments:** `stripe`, `razorpay`, `paypal`, `lemonsqueezy`
- **🔍 Search & Vector:** `serp_api`, `bing_search`, `algolia`, `pinecone`, `weaviate`
- **🔧 Misc:** `github`, `slack`, `discord`, `custom`

*(If a provider isn't strictly typed, it will safely fallback to `"custom"`, though you can also just pass `"custom"`).*

</details>
