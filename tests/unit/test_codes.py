"""The short-code generator: right shape, right characters, no obvious patterns."""

import string

from tinyurl_py.domain.codes import ALPHABET, CODE_LENGTH, generate_code

SAMPLE_SIZE = 1000


def test_code_has_the_expected_length() -> None:
    assert CODE_LENGTH == 7
    assert len(generate_code()) == CODE_LENGTH


def test_alphabet_is_exactly_the_62_letters_and_digits() -> None:
    assert len(ALPHABET) == 62
    assert set(ALPHABET) == set(string.ascii_letters + string.digits)


def test_code_uses_only_alphabet_characters() -> None:
    for _ in range(SAMPLE_SIZE):
        assert set(generate_code()) <= set(ALPHABET)


def test_codes_are_not_repeating() -> None:
    # 1000 codes out of ~3.5 trillion possibilities: a repeat is astronomically
    # unlikely, so any duplicate means the generator is broken (constant,
    # counter that restarts, tiny alphabet...).
    codes = {generate_code() for _ in range(SAMPLE_SIZE)}

    assert len(codes) == SAMPLE_SIZE


def test_codes_mix_uppercase_lowercase_and_digits() -> None:
    # Catches a generator that quietly uses only part of the alphabet.
    seen = set("".join(generate_code() for _ in range(SAMPLE_SIZE)))

    assert seen & set(string.ascii_uppercase)
    assert seen & set(string.ascii_lowercase)
    assert seen & set(string.digits)
