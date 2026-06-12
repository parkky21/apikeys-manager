"""Enterprise API key management: rotation, rate-limiting, usage tracking, multi-backend storage.

A reusable Python library for managing API keys across all your business services.
Built with uv, supports multiple storage backends, and provides round-robin rotation,
rate limiting, usage tracking, concurrent usage control, and rich metadata.
"""

from __future__ import annotations

from .client import APIServiceHandler, SyncAPIServiceHandler
from .config import ASHConfig, get_config_from_env
from .enums import Environment, KeyStatus, Provider, RotationStrategy, StorageBackend
from .exceptions import (
    APIServiceHandlerError,
    DuplicateKeyError,
    EncryptionError,
    InvalidProviderError,
    KeyExpiredError,
    KeyNotFoundError,
    MaxConcurrentExceededError,
    NoAvailableKeyError,
    RateLimitExceededError,
    StorageConnectionError,
    StorageNotInitializedError,
)
from .models import (
    APIKey,
    BulkOperationResult,
    KeyCreateRequest,
    KeyFilter,
    KeyUpdateRequest,
    UsageStats,
)

import importlib.metadata

try:
    __version__ = importlib.metadata.version("api-service-handler")
except importlib.metadata.PackageNotFoundError:
    __version__ = "unknown"
__all__ = [
    # Main clients
    "APIServiceHandler",
    "SyncAPIServiceHandler",
    
    # Configuration
    "ASHConfig",
    "get_config_from_env",
    
    # Enums
    "Environment",
    "KeyStatus",
    "Provider",
    "RotationStrategy",
    "StorageBackend",
    
    # Models
    "APIKey",
    "BulkOperationResult",
    "KeyCreateRequest",
    "KeyFilter",
    "KeyUpdateRequest",
    "UsageStats",
    
    # Exceptions
    "APIServiceHandlerError",
    "DuplicateKeyError",
    "EncryptionError",
    "InvalidProviderError",
    "KeyExpiredError",
    "KeyNotFoundError",
    "MaxConcurrentExceededError",
    "NoAvailableKeyError",
    "RateLimitExceededError",
    "StorageConnectionError",
    "StorageNotInitializedError",
]
