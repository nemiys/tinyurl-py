"""Request and response shapes of the HTTP API.

These are separate from what is stored in Mongo (see wikiguard-py ADR-0005):
the stored user document carries a password hash, and nothing here may ever
expose it. Pydantic checks every incoming request against these classes and
FastAPI answers 422 with an explanation when a request does not fit.
"""

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

# Min 8: length matters more than character-class rules. Max 128: hashing
# time grows with input size, so an absurdly long password is a cheap way to
# slow the server down.
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128


class RegisterRequest(BaseModel):
    email: EmailStr = Field(examples=["dana@example.com"])
    password: str = Field(
        min_length=PASSWORD_MIN_LENGTH,
        max_length=PASSWORD_MAX_LENGTH,
        examples=["correct horse battery staple"],
    )


class UserPublic(BaseModel):
    """A user as the outside world may see them: no password, no hash."""

    id: str
    email: EmailStr
    created_at: datetime
