"""Local development settings."""

from .base import *

# The front end generates its API types from the schema (`npm run api:types`).
SERVE_API_SCHEMA = True

# The development server answers over plain HTTP.
REFRESH_COOKIE_SECURE = False
