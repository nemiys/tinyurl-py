"""The JWT secret must be long enough to be a real key."""

import pytest
from pydantic import ValidationError

from tinyurl_py.settings import Settings


def make(secret: str) -> Settings:
    # _env_file=None: judge only the value given here, never a local .env.
    return Settings(_env_file=None, jwt_secret=secret)


def test_an_empty_secret_is_refused() -> None:
    # What a copied .env.example gives: "JWT_SECRET=" with nothing after it.
    with pytest.raises(ValidationError, match="jwt_secret"):
        make("")


def test_a_short_secret_is_refused() -> None:
    with pytest.raises(ValidationError, match="jwt_secret"):
        make("x" * 31)


def test_a_32_character_secret_is_accepted() -> None:
    assert make("x" * 32).jwt_secret == "x" * 32
