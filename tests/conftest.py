"""Shared test setup.

The app refuses to start without a JWT secret (see settings.py), so tests
provide their own throwaway one. `setdefault` keeps a real value if somebody
exported one. This must run before the app's settings are first imported,
which is why it lives in conftest.py: pytest loads it before any test module.
"""

import os

os.environ.setdefault("JWT_SECRET", "test-only-secret-key-that-is-long-enough-for-hs256")
