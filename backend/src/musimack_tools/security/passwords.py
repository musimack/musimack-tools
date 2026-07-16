"""Strict standard-library password and opaque-session primitives."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets

from musimack_tools.domain.authentication import (
    PASSWORD_ALGORITHM,
    PASSWORD_FORMAT_VERSION,
    PasswordHash,
)

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_SALT_RE = re.compile(r"^[0-9a-f]{32}$")
_TOKEN_RE = re.compile(r"^session-[0-9a-f]{64}$")
_MAXIMUM_HASH_ITERATIONS = 10_000_000


def hash_password(password: str, *, iterations: int = 600_000) -> PasswordHash:
    if iterations < 1:
        raise ValueError("authentication_password_iterations_invalid")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return PasswordHash(digest.hex(), salt.hex(), iterations)


def verify_password(password: str, stored: PasswordHash) -> bool:
    if (
        stored.algorithm != PASSWORD_ALGORITHM
        or stored.version != PASSWORD_FORMAT_VERSION
        or not _SALT_RE.fullmatch(stored.salt_hex)
        or not _HASH_RE.fullmatch(stored.encoded_hash)
        or not 1 <= stored.iterations <= _MAXIMUM_HASH_ITERATIONS
    ):
        return False
    candidate = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(stored.salt_hex), stored.iterations
    ).hex()
    return hmac.compare_digest(candidate, stored.encoded_hash)


def new_session_token() -> str:
    return f"session-{secrets.token_hex(32)}"


def session_token_hash(token: str) -> str:
    if not _TOKEN_RE.fullmatch(token):
        raise ValueError("authentication_session_invalid")
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def valid_session_token(token: str) -> bool:
    return _TOKEN_RE.fullmatch(token) is not None
