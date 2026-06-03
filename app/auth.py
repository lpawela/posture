"""Password hashing and opaque session tokens — stdlib only.

PBKDF2-HMAC-SHA256 for passwords (no third-party crypto dependency) and
``secrets`` for tokens. Good enough for a skeleton; swap for a vetted auth
library before production.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

_ITERATIONS = 100_000


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """Return ``(salt_hex, hash_hex)`` for ``password``.

    A fresh random salt is generated unless one is supplied (used by
    :func:`verify_password`).
    """
    if salt is None:
        salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), _ITERATIONS
    )
    return salt, digest.hex()


def verify_password(password: str, salt: str, expected_hash: str) -> bool:
    """Constant-time check of ``password`` against a stored salt/hash."""
    _, candidate = hash_password(password, salt)
    return hmac.compare_digest(candidate, expected_hash)


def new_token() -> str:
    """A fresh, URL-safe opaque session token."""
    return secrets.token_urlsafe(32)
