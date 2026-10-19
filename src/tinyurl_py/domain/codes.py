"""Short code generation.

Pure logic with no database or network, so it is quick to test.
"""

import secrets
import string

# 26 lowercase + 26 uppercase + 10 digits = 62 characters ("base62").
ALPHABET = string.ascii_letters + string.digits
# 62 ** 7 is about 3.5 trillion possible codes.
CODE_LENGTH = 7


def generate_code() -> str:
    # `secrets` draws from the operating system's secure randomness. Plain
    # `random` follows a known formula, so someone who sees enough codes can
    # predict the next ones, and guessing other people's links must stay hard.
    return "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))


def is_valid_code(code: str) -> bool:
    """Could this text be a code we generated? Cheap check that lets the
    redirect reject junk like "favicon.ico" without touching Redis or Mongo."""
    return len(code) == CODE_LENGTH and all(character in ALPHABET for character in code)
