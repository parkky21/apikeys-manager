"""AES-256-GCM encryption utilities for the API Service Handler.

API key values are encrypted at rest using a symmetric key derived from a
shared secret.  The encrypted representation is a dot-separated triple of
Base-64 segments::

    <iv_b64>.<auth_tag_b64>.<ciphertext_b64>

This format is deterministic enough to be detected by :func:`is_encrypted`
yet safe against accidental double-encryption because plain API keys never
contain two dots separating valid Base-64 segments.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_IV_BYTES: int = 12          # 96-bit nonce recommended for AES-GCM
_TAG_BYTES: int = 16         # 128-bit authentication tag
_KEY_BYTES: int = 32         # 256-bit key (AES-256)

# Loose regex for a Base-64 segment (standard or URL-safe, with optional padding)
_B64_SEGMENT = r"[A-Za-z0-9+/\-_]+=*"
_ENCRYPTED_PATTERN: re.Pattern[str] = re.compile(
    rf"^{_B64_SEGMENT}\.{_B64_SEGMENT}\.{_B64_SEGMENT}$"
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _derive_key(shared_secret: str) -> bytes:
    """Derive a 256-bit AES key from *shared_secret* via SHA-256.

    Parameters
    ----------
    shared_secret:
        The passphrase to derive the key from.  Must be non-empty.

    Returns
    -------
    bytes
        A 32-byte key suitable for ``AESGCM``.

    Raises
    ------
    ValueError
        If *shared_secret* is empty.
    """
    if not shared_secret:
        raise ValueError("shared_secret must not be empty for encryption/decryption.")
    return hashlib.sha256(shared_secret.encode("utf-8")).digest()


def _b64_encode(data: bytes) -> str:
    """Return standard Base-64 encoding of *data* as a UTF-8 string."""
    return base64.b64encode(data).decode("utf-8")


def _b64_decode(data: str) -> bytes:
    """Decode a standard Base-64 string to bytes."""
    return base64.b64decode(data)


# ---------------------------------------------------------------------------
# Public API – encrypt / decrypt
# ---------------------------------------------------------------------------


def encrypt_api_key(plain_text: str, shared_secret: str) -> str:
    """Encrypt *plain_text* with AES-256-GCM using a key derived from *shared_secret*.

    Parameters
    ----------
    plain_text:
        The raw API key (or any secret) to encrypt.
    shared_secret:
        Passphrase used to derive the encryption key.

    Returns
    -------
    str
        The encrypted payload formatted as ``iv_b64.auth_tag_b64.ciphertext_b64``.

    Raises
    ------
    ValueError
        If *shared_secret* is empty.
    """
    key = _derive_key(shared_secret)
    iv = os.urandom(_IV_BYTES)

    aesgcm = AESGCM(key)
    # AESGCM.encrypt returns ciphertext || tag (tag is the last 16 bytes)
    ciphertext_with_tag: bytes = aesgcm.encrypt(iv, plain_text.encode("utf-8"), None)

    # Split into ciphertext body + authentication tag
    ciphertext = ciphertext_with_tag[:-_TAG_BYTES]
    auth_tag = ciphertext_with_tag[-_TAG_BYTES:]

    return f"{_b64_encode(iv)}.{_b64_encode(auth_tag)}.{_b64_encode(ciphertext)}"


def decrypt_api_key(encrypted_str: str, shared_secret: str) -> str:
    """Decrypt an encrypted payload produced by :func:`encrypt_api_key`.

    The function is intentionally *lenient*:

    * If *encrypted_str* is not a string, or does not look like an encrypted
      triple, it is returned unchanged.
    * If decryption fails for **any** reason (wrong secret, corrupted data,
      etc.) the original *encrypted_str* is returned unchanged.  This enables
      graceful handling of already-decrypted or plain-text values.

    Parameters
    ----------
    encrypted_str:
        The dot-separated encrypted payload, or a plain-text fallback.
    shared_secret:
        Passphrase used to derive the decryption key.

    Returns
    -------
    str
        The decrypted plain text, or *encrypted_str* unchanged on failure.
    """
    # Guard: not a string → return as-is
    if not isinstance(encrypted_str, str):
        return encrypted_str  # type: ignore[return-value]

    # Guard: must be exactly three dot-separated segments
    parts = encrypted_str.split(".")
    if len(parts) != 3:
        return encrypted_str

    try:
        iv = _b64_decode(parts[0])
        auth_tag = _b64_decode(parts[1])
        ciphertext = _b64_decode(parts[2])

        key = _derive_key(shared_secret)
        aesgcm = AESGCM(key)

        # Reconstruct the format AESGCM expects: ciphertext || tag
        ciphertext_with_tag = ciphertext + auth_tag
        decrypted_bytes: bytes = aesgcm.decrypt(iv, ciphertext_with_tag, None)

        # Try to deserialise as JSON first (handles stored dicts / lists)
        try:
            result: Any = json.loads(decrypted_bytes)
            return str(result) if not isinstance(result, str) else result
        except (json.JSONDecodeError, UnicodeDecodeError):
            return decrypted_bytes.decode("utf-8")

    except Exception:  # noqa: BLE001 – intentionally broad
        return encrypted_str


# ---------------------------------------------------------------------------
# Public API – inspection helpers
# ---------------------------------------------------------------------------


def is_encrypted(value: str) -> bool:
    """Check whether *value* looks like an encrypted payload.

    This is a *heuristic* based on the ``iv.tag.ciphertext`` format — three
    dot-separated Base-64 segments — and does **not** attempt actual
    decryption.

    Parameters
    ----------
    value:
        The string to inspect.

    Returns
    -------
    bool
        ``True`` if *value* matches the encrypted format.
    """
    if not isinstance(value, str):
        return False
    return bool(_ENCRYPTED_PATTERN.match(value))


def mask_key(key_value: str, show: int = 8) -> str:
    """Return a masked representation of *key_value* suitable for display.

    Parameters
    ----------
    key_value:
        The API key (plain text or encrypted) to mask.
    show:
        Number of leading characters to reveal.  Defaults to ``8``.

    Returns
    -------
    str
        The first *show* characters followed by ``***``, or the full value
        if it is shorter than or equal to *show* characters.

    Examples
    --------
    >>> mask_key("sk-abc123def456ghi789")
    'sk-abc12***'
    >>> mask_key("short")
    'short'
    """
    if not isinstance(key_value, str) or len(key_value) <= show:
        return key_value
    return key_value[:show] + "***"
