"""Custom exceptions for the api-service-handler library.

Every exception inherits from :class:`APIServiceHandlerError` so callers
can catch the entire family with a single ``except`` clause when desired.
Each concrete exception stores structured context as instance attributes
and generates a clear, actionable error message.
"""

from __future__ import annotations


class APIServiceHandlerError(Exception):
    """Base exception for all api-service-handler errors.

    All library-specific exceptions inherit from this class, making it
    easy to catch any error raised by the library::

        try:
            key = await manager.get_key("openai")
        except APIServiceHandlerError as exc:
            logging.error("Service handler failure: %s", exc)
    """

    def __init__(self, message: str = "An API service handler error occurred") -> None:
        self.message = message
        super().__init__(self.message)


class KeyNotFoundError(APIServiceHandlerError):
    """Raised when a key with the given ID does not exist in storage.

    Attributes:
        key_id: The identifier that was looked up.
    """

    def __init__(self, key_id: str) -> None:
        self.key_id = key_id
        super().__init__(f"API key not found: '{key_id}'")


class DuplicateKeyError(APIServiceHandlerError):
    """Raised when attempting to register a key that already exists.

    A key is considered duplicate when the same ``key_value`` is already
    registered for the given ``provider``.

    Attributes:
        provider: The provider for which the duplicate was detected.
    """

    def __init__(self, provider: str, key_value: str | None = None) -> None:
        self.provider = provider
        self.key_value = key_value
        msg = f"A key with the same value already exists for provider '{provider}'"
        if key_value:
            masked = key_value[:8] + "***" if len(key_value) > 8 else key_value[:2] + "***"
            msg = f"Key '{masked}' already exists for provider '{provider}'"
        super().__init__(msg)


class RateLimitExceededError(APIServiceHandlerError):
    """Raised when a key has exceeded its daily or monthly usage limit.

    Attributes:
        key_id: The key that hit the limit.
        limit_type: Either ``'daily'`` or ``'monthly'``.
    """

    def __init__(
        self,
        key_id: str,
        limit_type: str,
        limit: int | None = None,
        current: int | None = None,
    ) -> None:
        self.key_id = key_id
        self.limit_type = limit_type
        self.limit = limit
        self.current = current
        msg = f"API key '{key_id}' has exceeded its {limit_type} rate limit"
        if limit is not None:
            msg += f" (limit: {limit}, current: {current})"
        super().__init__(msg)


class MaxConcurrentExceededError(APIServiceHandlerError):
    """Raised when a key's concurrent usage equals or exceeds its maximum.

    Attributes:
        key_id: The key that is at capacity.
        max_concurrent: The configured concurrency ceiling.
    """

    def __init__(self, key_id: str, max_concurrent: int) -> None:
        self.key_id = key_id
        self.max_concurrent = max_concurrent
        super().__init__(
            f"API key '{key_id}' has reached its maximum concurrent usage "
            f"of {max_concurrent}"
        )


class NoAvailableKeyError(APIServiceHandlerError):
    """Raised when no active key is available for the requested provider.

    Attributes:
        provider: The provider for which no key could be found.
    """

    def __init__(self, provider: str) -> None:
        self.provider = provider
        super().__init__(
            f"No available API key for provider '{provider}'"
        )


class StorageConnectionError(APIServiceHandlerError):
    """Raised when the storage backend cannot be reached.

    Attributes:
        backend: Name of the storage backend (e.g. ``'postgresql'``).
    """

    def __init__(self, backend: str, detail: str | None = None, details: str | None = None) -> None:
        self.backend = backend
        self.detail = detail or details
        msg = f"Failed to connect to storage backend '{backend}'"
        if self.detail:
            msg += f": {self.detail}"
        super().__init__(msg)


class EncryptionError(APIServiceHandlerError):
    """Raised when an encryption or decryption operation fails.

    This may indicate a missing or invalid encryption key, corrupted
    ciphertext, or an unsupported algorithm.
    """

    def __init__(self, detail: str = "Encryption/decryption operation failed") -> None:
        self.detail = detail
        super().__init__(detail)


class InvalidProviderError(APIServiceHandlerError):
    """Raised when an unrecognised provider string is used in a strict context.

    Attributes:
        provider: The invalid provider string that was supplied.
    """

    def __init__(self, provider: str) -> None:
        self.provider = provider
        super().__init__(
            f"Invalid or unknown provider: '{provider}'"
        )


class KeyExpiredError(APIServiceHandlerError):
    """Raised when an API key is past its ``expires_at`` timestamp.

    Attributes:
        key_id: The expired key's identifier.
    """

    def __init__(self, key_id: str) -> None:
        self.key_id = key_id
        super().__init__(
            f"API key '{key_id}' has expired"
        )


class StorageNotInitializedError(APIServiceHandlerError):
    """Raised when a storage operation is attempted before initialization.

    Callers must invoke ``storage.initialize()`` (or its async counterpart)
    before performing any read/write operations.
    """

    def __init__(self) -> None:
        super().__init__(
            "Storage backend has not been initialized. "
            "Call 'storage.initialize()' before performing operations."
        )
