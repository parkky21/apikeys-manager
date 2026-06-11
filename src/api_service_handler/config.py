"""Configuration module for the API Service Handler.

Provides :class:`ASHConfig` — a dataclass holding every tuneable knob — and
the helper :func:`get_config_from_env` that builds an ``ASHConfig`` purely
from environment variables prefixed with ``ASH_``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Supported literal values (kept as module-level constants for validation)
# ---------------------------------------------------------------------------

VALID_STORAGE_BACKENDS = frozenset({"memory", "sqlite", "mongodb", "postgresql"})
VALID_ROTATION_STRATEGIES = frozenset({"round_robin", "least_used", "random", "weighted"})


# ---------------------------------------------------------------------------
# Core configuration dataclass
# ---------------------------------------------------------------------------


@dataclass
class ASHConfig:
    """Configuration for the API Service Handler.

    Attributes
    ----------
    storage_backend:
        Which persistence layer to use.  One of ``memory``, ``sqlite``,
        ``mongodb``, or ``postgresql``.  Falls back to the
        ``ASH_STORAGE_BACKEND`` env var when set to ``"memory"`` (the default).
    connection_string:
        Database connection URI.  Falls back to ``ASH_CONNECTION_STRING``.
    shared_secret:
        Passphrase used to derive an AES-256-GCM key for encrypting stored API
        keys.  Falls back to ``ASH_SHARED_SECRET``.
    encrypt_keys:
        Whether API key values should be encrypted at rest.
    rotation_strategy:
        Algorithm used when picking the next key.  One of ``round_robin``,
        ``least_used``, ``random``, or ``weighted``.
    auto_reset_counters:
        Automatically reset daily / monthly usage counters on access when the
        current period has elapsed.
    soft_delete:
        When ``True``, deleting a key sets its status to ``REVOKED`` rather
        than removing the record.
    default_daily_limit:
        Default daily request cap applied to newly created keys.
    default_monthly_limit:
        Default monthly request cap applied to newly created keys.
    default_max_concurrent:
        Default maximum number of concurrent in-flight requests per key.
    """

    # Storage
    storage_backend: str = "memory"
    connection_string: str = ""

    # Encryption
    shared_secret: str = ""
    encrypt_keys: bool = True

    # Rotation
    rotation_strategy: str = "round_robin"

    # Behaviour
    auto_reset_counters: bool = True
    soft_delete: bool = True
    default_daily_limit: Optional[int] = None
    default_monthly_limit: Optional[int] = None
    default_max_concurrent: Optional[int] = None

    # ------------------------------------------------------------------
    # Post-init: resolve env-var fallbacks & validate
    # ------------------------------------------------------------------

    def __post_init__(self) -> None:
        # Env-var fallbacks
        if not self.shared_secret:
            self.shared_secret = os.environ.get("ASH_SHARED_SECRET", "")
        if not self.connection_string:
            self.connection_string = os.environ.get("ASH_CONNECTION_STRING", "")
        if self.storage_backend == "memory":
            self.storage_backend = os.environ.get("ASH_STORAGE_BACKEND", "memory")

        # Normalise & validate
        self.storage_backend = self.storage_backend.lower().strip()
        self.rotation_strategy = self.rotation_strategy.lower().strip()

        if self.storage_backend not in VALID_STORAGE_BACKENDS:
            raise ValueError(
                f"Invalid storage_backend {self.storage_backend!r}. "
                f"Choose from {sorted(VALID_STORAGE_BACKENDS)}."
            )
        if self.rotation_strategy not in VALID_ROTATION_STRATEGIES:
            raise ValueError(
                f"Invalid rotation_strategy {self.rotation_strategy!r}. "
                f"Choose from {sorted(VALID_ROTATION_STRATEGIES)}."
            )

        # Limit fields must be non-negative when set
        for attr in ("default_daily_limit", "default_monthly_limit", "default_max_concurrent"):
            value = getattr(self, attr)
            if value is not None and value < 0:
                raise ValueError(f"{attr} must be a non-negative integer, got {value}.")


# ---------------------------------------------------------------------------
# Factory – build config entirely from environment variables
# ---------------------------------------------------------------------------


def _env_bool(name: str, default: bool) -> bool:
    """Read an env var as a boolean (``true/1/yes`` → True)."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"true", "1", "yes"}


def _env_optional_int(name: str) -> Optional[int]:
    """Read an env var as an optional integer."""
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return None
    try:
        return int(raw)
    except ValueError:
        raise ValueError(
            f"Environment variable {name} must be an integer, got {raw!r}."
        ) from None


def get_config_from_env() -> ASHConfig:
    """Build an :class:`ASHConfig` entirely from ``ASH_*`` environment variables.

    Recognised variables
    --------------------
    * ``ASH_STORAGE_BACKEND``   – storage backend name
    * ``ASH_CONNECTION_STRING`` – database connection URI
    * ``ASH_SHARED_SECRET``     – encryption passphrase
    * ``ASH_ENCRYPT_KEYS``      – ``true`` / ``false``
    * ``ASH_ROTATION_STRATEGY`` – rotation algorithm name
    * ``ASH_AUTO_RESET_COUNTERS`` – ``true`` / ``false``
    * ``ASH_SOFT_DELETE``       – ``true`` / ``false``
    * ``ASH_DEFAULT_DAILY_LIMIT``
    * ``ASH_DEFAULT_MONTHLY_LIMIT``
    * ``ASH_DEFAULT_MAX_CONCURRENT``

    Returns
    -------
    ASHConfig
        A fully populated configuration instance.
    """
    return ASHConfig(
        storage_backend=os.environ.get("ASH_STORAGE_BACKEND", "memory"),
        connection_string=os.environ.get("ASH_CONNECTION_STRING", ""),
        shared_secret=os.environ.get("ASH_SHARED_SECRET", ""),
        encrypt_keys=_env_bool("ASH_ENCRYPT_KEYS", default=True),
        rotation_strategy=os.environ.get("ASH_ROTATION_STRATEGY", "round_robin"),
        auto_reset_counters=_env_bool("ASH_AUTO_RESET_COUNTERS", default=True),
        soft_delete=_env_bool("ASH_SOFT_DELETE", default=True),
        default_daily_limit=_env_optional_int("ASH_DEFAULT_DAILY_LIMIT"),
        default_monthly_limit=_env_optional_int("ASH_DEFAULT_MONTHLY_LIMIT"),
        default_max_concurrent=_env_optional_int("ASH_DEFAULT_MAX_CONCURRENT"),
    )
