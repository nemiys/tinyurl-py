"""Password hashing with argon2 (via pwdlib).

Only the hash is ever stored. argon2 is slow on purpose and mixes in a random
salt, so guessing passwords from a stolen database is expensive. The hash
string also records the algorithm settings, so old hashes keep verifying
after the settings are tuned.

These calls take a noticeable fraction of a second and block while they run,
so callers inside async endpoints should wrap them in `asyncio.to_thread`.
"""

from pwdlib import PasswordHash

# `recommended()` is pwdlib's argon2 setup with sensible parameters.
_hasher = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _hasher.verify(password, password_hash)
