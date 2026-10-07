"""Test suite settings: same PostgreSQL engine as production."""

from .base import *

# The tests verify that the API contract is exposed.
SERVE_API_SCHEMA = True

# Real password hashing dominates the suite's running time.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
