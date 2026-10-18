"""Login tokens (JWT).

A token states "this request belongs to user X until time T" and carries a
signature made with our secret key. Nothing is stored on the server: to check
a token we recompute the signature, so a forged or edited token fails.
The payload is only signed, not encrypted: never put anything private in it.
"""

from datetime import UTC, datetime, timedelta

import jwt

from tinyurl_py.settings import settings

ALGORITHM = "HS256"


class InvalidTokenError(Exception):
    """The token is forged, edited, expired, or not a token at all."""


def create_access_token(user_id: str, expires_in: timedelta | None = None) -> str:
    now = datetime.now(UTC)
    lifetime = (
        expires_in if expires_in is not None else timedelta(minutes=settings.jwt_expire_minutes)
    )
    claims = {
        "sub": user_id,  # "subject": who the token is about
        "iat": now,  # "issued at"
        "exp": now + lifetime,  # "expires at"; PyJWT checks it when decoding
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm=ALGORITHM)


def decode_access_token(token: str) -> str:
    """Return the user id inside a valid token, or raise InvalidTokenError."""
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            # Always name the allowed algorithm ourselves; never trust the one
            # the token's header claims (a classic JWT attack).
            algorithms=[ALGORITHM],
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWTError as error:
        raise InvalidTokenError(str(error)) from error
    return str(claims["sub"])
