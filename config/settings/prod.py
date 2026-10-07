"""Production and preproduction settings: gunicorn behind nginx, over HTTPS."""

from .base import *

DEBUG = False

# nginx terminates TLS, redirects HTTP to HTTPS and forwards the original scheme.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True

# One reverse proxy (nginx) stands in front of gunicorn: client IPs used by the
# throttles are read from X-Forwarded-For accordingly.
NINJA_NUM_PROXIES = 1

SILENCED_SYSTEM_CHECKS = [
    # The HTTP to HTTPS redirect is done by nginx, before Django is reached.
    "security.W008",
    # The domain is not submitted to the browsers' HSTS preload list.
    "security.W021",
]
