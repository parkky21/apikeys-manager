"""Enumerations for the api-service-handler library.

Defines all enum types used across the library including API providers,
key statuses, storage backends, rotation strategies, and environments.
"""

from __future__ import annotations

from enum import Enum


class Provider(str, Enum):
    """Supported API service providers.

    Covers a wide range of provider categories including AI/LLM, speech/audio,
    cloud infrastructure, communication, payments, search/data, auth,
    storage/CDN, dev tools, messaging, productivity, monitoring, and maps.

    Use ``Provider.from_string()`` for case-insensitive lookup with automatic
    fallback to ``CUSTOM`` for unrecognised values.
    """

    # --- AI / LLM ---
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE_GEMINI = "google_gemini"
    GOOGLE_VERTEX = "google_vertex"
    MISTRAL = "mistral"
    COHERE = "cohere"
    HUGGINGFACE = "huggingface"
    REPLICATE = "replicate"
    TOGETHER_AI = "together_ai"
    GROQ = "groq"
    FIREWORKS = "fireworks"
    DEEPSEEK = "deepseek"
    XAI = "xai"
    PERPLEXITY = "perplexity"
    OPENROUTER = "openrouter"

    # --- Speech / Audio ---
    DEEPGRAM = "deepgram"
    ELEVEN_LABS = "eleven_labs"
    ASSEMBLY_AI = "assembly_ai"
    WHISPER = "whisper"

    # --- Cloud ---
    AWS = "aws"
    AZURE = "azure"
    GCP = "gcp"
    CLOUDFLARE = "cloudflare"
    DIGITAL_OCEAN = "digital_ocean"
    VERCEL = "vercel"

    # --- Communication ---
    TWILIO = "twilio"
    SENDGRID = "sendgrid"
    MAILGUN = "mailgun"
    RESEND = "resend"
    POSTMARK = "postmark"

    # --- Payments ---
    STRIPE = "stripe"
    RAZORPAY = "razorpay"
    PAYPAL = "paypal"
    LEMONSQUEEZY = "lemonsqueezy"

    # --- Search / Data ---
    SERP_API = "serp_api"
    BING_SEARCH = "bing_search"
    ALGOLIA = "algolia"
    PINECONE = "pinecone"
    WEAVIATE = "weaviate"

    # --- Auth ---
    AUTH0 = "auth0"
    CLERK = "clerk"
    FIREBASE = "firebase"
    SUPABASE_AUTH = "supabase_auth"

    # --- Storage / CDN ---
    CLOUDINARY = "cloudinary"
    S3 = "s3"
    SUPABASE = "supabase"
    R2 = "r2"
    UPLOADTHING = "uploadthing"

    # --- Dev Tools ---
    GITHUB = "github"
    GITLAB = "gitlab"
    BITBUCKET = "bitbucket"
    LINEAR = "linear"
    JIRA = "jira"

    # --- Messaging ---
    SLACK = "slack"
    DISCORD = "discord"
    TELEGRAM = "telegram"
    WHATSAPP = "whatsapp"

    # --- Productivity ---
    NOTION = "notion"
    AIRTABLE = "airtable"
    ZAPIER = "zapier"
    MAKE = "make"

    # --- Monitoring ---
    SENTRY = "sentry"
    DATADOG = "datadog"
    NEW_RELIC = "new_relic"
    LOGFLARE = "logflare"

    # --- Maps ---
    GOOGLE_MAPS = "google_maps"
    MAPBOX = "mapbox"
    HERE = "here"

    # --- Catch-all ---
    CUSTOM = "custom"

    @classmethod
    def from_string(cls, value: str) -> Provider:
        """Look up a provider by name (case-insensitive).

        Attempts to match *value* against both the enum member **name**
        (e.g. ``"OPENAI"``) and the enum member **value** (e.g. ``"openai"``).
        Returns :attr:`Provider.CUSTOM` when no match is found.

        Args:
            value: The provider string to look up.

        Returns:
            The matching ``Provider`` member, or ``Provider.CUSTOM``.

        Examples:
            >>> Provider.from_string("openai")
            <Provider.OPENAI: 'openai'>
            >>> Provider.from_string("ANTHROPIC")
            <Provider.ANTHROPIC: 'anthropic'>
            >>> Provider.from_string("unknown_service")
            <Provider.CUSTOM: 'custom'>
        """
        normalised = value.strip().upper()

        # Fast path: match by member name (e.g. "OPENAI", "GOOGLE_GEMINI").
        try:
            return cls[normalised]
        except KeyError:
            pass

        # Slower path: match by member value (lowercase form).
        lower = value.strip().lower()
        for member in cls:
            if member.value == lower:
                return member

        return cls.CUSTOM


class KeyStatus(str, Enum):
    """Status of an API key in the key pool."""

    ACTIVE = "active"
    """Key is available for use."""

    INACTIVE = "inactive"
    """Key has been manually disabled."""

    RATE_LIMITED = "rate_limited"
    """Key has hit a rate limit and is temporarily unavailable."""

    EXPIRED = "expired"
    """Key has passed its expiration date."""

    REVOKED = "revoked"
    """Key has been permanently revoked by the provider or admin."""


class StorageBackend(str, Enum):
    """Supported storage backends for persisting key data."""

    MEMORY = "memory"
    """In-process dictionary — useful for testing and single-process apps."""

    SQLITE = "sqlite"
    """SQLite file-based database."""

    MONGODB = "mongodb"
    """MongoDB document store."""

    POSTGRESQL = "postgresql"
    """PostgreSQL relational database."""


class RotationStrategy(str, Enum):
    """Strategy for selecting the next API key from the pool."""

    ROUND_ROBIN = "round_robin"
    """Cycle through keys in order."""

    LEAST_USED = "least_used"
    """Pick the key with the fewest total uses."""

    RANDOM = "random"
    """Pick a key at random."""

    WEIGHTED = "weighted"
    """Pick a key based on assigned weights / priorities."""


class Environment(str, Enum):
    """Application deployment environment."""

    PRODUCTION = "production"
    STAGING = "staging"
    DEVELOPMENT = "development"
    TESTING = "testing"
