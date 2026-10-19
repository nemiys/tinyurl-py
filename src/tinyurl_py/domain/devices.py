"""Device detection from the User-Agent header."""


def is_mobile(user_agent: str | None) -> bool:
    """True for phones. Mozilla's own advice is to look for "Mobi" anywhere in
    the header: phones include it, desktops do not. Tablets (e.g. iPads, which
    pose as desktops) are deliberately not counted as mobile. Kept in one
    function so a smarter detector can replace it later without touching callers."""
    return user_agent is not None and "Mobi" in user_agent
