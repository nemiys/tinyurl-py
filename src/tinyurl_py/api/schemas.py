"""Request and response shapes of the HTTP API.

These are separate from what is stored in Mongo (see wikiguard-py ADR-0005):
the stored user document carries a password hash, and nothing here may ever
expose it. Pydantic checks every incoming request against these classes and
FastAPI answers 422 with an explanation when a request does not fit.
"""

from datetime import UTC, datetime

from pydantic import AwareDatetime, BaseModel, EmailStr, Field, HttpUrl, field_validator

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


class LoginRequest(BaseModel):
    email: EmailStr = Field(examples=["dana@example.com"])
    # No minimum here: login must not reveal the password rules. The maximum
    # stays so nobody can make the server hash a huge input.
    password: str = Field(max_length=PASSWORD_MAX_LENGTH, examples=["correct horse battery staple"])


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserPublic(BaseModel):
    """A user as the outside world may see them: no password, no hash."""

    id: str
    email: EmailStr
    created_at: datetime


class CreateLinkRequest(BaseModel):
    # HttpUrl accepts only http/https and caps the length at 2083 characters, so
    # `javascript:`, `data:` and `ftp:` links are rejected. Blocking internal
    # addresses such as http://localhost is still to do (stage 7).
    url: HttpUrl = Field(examples=["https://example.com/products/summer-sale"])
    # Smart-link rule: visitors on a mobile device are sent here instead.
    mobile_url: HttpUrl | None = Field(default=None, examples=["https://m.example.com/summer"])
    # AwareDatetime requires a timezone ("...Z" or "+02:00"): a bare "10:00" is ambiguous.
    expires_at: AwareDatetime | None = Field(default=None, examples=["2030-12-01T10:00:00Z"])

    @field_validator("expires_at")
    @classmethod
    def expiry_must_be_in_the_future(cls, value: AwareDatetime | None) -> AwareDatetime | None:
        if value is not None and value <= datetime.now(UTC):
            raise ValueError("expires_at must be in the future")
        return value


class LinkPublic(BaseModel):
    code: str = Field(examples=["aB3dE9x"])
    # What people share: base_url + "/" + code.
    short_url: str = Field(examples=["http://localhost:8001/aB3dE9x"])
    url: str
    mobile_url: str | None
    expires_at: AwareDatetime | None
    created_at: AwareDatetime


class LinkPage(BaseModel):
    """One page of links, plus what a client needs to build "page 3 of 12"."""

    items: list[LinkPublic]
    total: int  # all of the user's links, not just this page
    limit: int
    offset: int
