"""Rules for what the register endpoint accepts and what it may reveal."""

import pytest
from pydantic import ValidationError

from tinyurl_py.api.schemas import RegisterRequest, UserPublic


def test_valid_registration_is_accepted() -> None:
    request = RegisterRequest(email="dana@example.com", password="correct horse")

    assert request.email == "dana@example.com"


def test_email_that_is_not_an_email_is_rejected() -> None:
    with pytest.raises(ValidationError):
        RegisterRequest(email="not-an-email", password="correct horse")


@pytest.mark.parametrize("length", [7, 129])
def test_password_with_bad_length_is_rejected(length: int) -> None:
    with pytest.raises(ValidationError):
        RegisterRequest(email="dana@example.com", password="x" * length)


@pytest.mark.parametrize("length", [8, 128])
def test_password_at_the_length_limits_is_accepted(length: int) -> None:
    request = RegisterRequest(email="dana@example.com", password="x" * length)

    assert len(request.password) == length


def test_public_user_never_exposes_password_data() -> None:
    # Whatever is stored in Mongo, this is the only shape that leaves the API.
    assert set(UserPublic.model_fields) == {"id", "email", "created_at"}
