"""Access tokens: a valid one is accepted, anything forged or stale is not."""

import base64
import json
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from tinyurl_py.security.tokens import InvalidTokenError, create_access_token, decode_access_token
from tinyurl_py.settings import settings


def test_token_round_trips_the_user_id() -> None:
    token = create_access_token("user-123")

    assert decode_access_token(token) == "user-123"


def test_token_signed_with_another_key_is_rejected() -> None:
    forged = jwt.encode(
        {"sub": "user-123", "exp": datetime.now(UTC) + timedelta(minutes=5)},
        "a-completely-different-secret-key-of-enough-length",
        algorithm="HS256",
    )

    with pytest.raises(InvalidTokenError):
        decode_access_token(forged)


def test_token_whose_payload_was_edited_is_rejected() -> None:
    # Dan takes his own valid token and swaps in Dana's id. He cannot redo the
    # signature (he lacks the secret), so the old signature no longer matches.
    header, payload, signature = create_access_token("dan").split(".")
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    claims["sub"] = "dana"
    edited = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()

    with pytest.raises(InvalidTokenError):
        decode_access_token(f"{header}.{edited}.{signature}")


def test_expired_token_is_rejected() -> None:
    token = create_access_token("user-123", expires_in=timedelta(seconds=-1))

    with pytest.raises(InvalidTokenError):
        decode_access_token(token)


def test_token_without_a_subject_is_rejected() -> None:
    no_subject = jwt.encode(
        {"exp": datetime.now(UTC) + timedelta(minutes=5)},
        settings.jwt_secret,
        algorithm="HS256",
    )

    with pytest.raises(InvalidTokenError):
        decode_access_token(no_subject)


def test_text_that_is_not_a_token_is_rejected() -> None:
    with pytest.raises(InvalidTokenError):
        decode_access_token("definitely-not-a-token")
