"""Password hashing: what we store must never reveal the password."""

from tinyurl_py.security.passwords import hash_password, verify_password

PASSWORD = "correct horse battery staple"


def test_hash_is_an_argon2_hash_and_does_not_contain_the_password() -> None:
    password_hash = hash_password(PASSWORD)

    assert password_hash.startswith("$argon2")
    assert PASSWORD not in password_hash


def test_correct_password_verifies() -> None:
    password_hash = hash_password(PASSWORD)

    assert verify_password(PASSWORD, password_hash) is True


def test_wrong_password_is_rejected() -> None:
    password_hash = hash_password(PASSWORD)

    assert verify_password("correct horse battery stapl3", password_hash) is False


def test_same_password_gets_a_different_hash_each_time() -> None:
    # Proof that a random salt is mixed in: two users with the same password
    # do not end up with the same stored value.
    assert hash_password(PASSWORD) != hash_password(PASSWORD)
