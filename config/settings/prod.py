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

# The private files live outside the release, in shared/private: no default, a
# release without the setting fails at once rather than writing into itself.
MEDIA_ROOT = Path(env("MEDIA_ROOT"))
# nginx's internal location for them (deploy/nginx/cdf3.conf.template).
PRIVATE_FILES_ACCEL_PREFIX = "/_private/"
# Readable by the API's user and by nginx's group alone (deploy/README.md).
FILE_UPLOAD_PERMISSIONS = 0o640
FILE_UPLOAD_DIRECTORY_PERMISSIONS = 0o750

SILENCED_SYSTEM_CHECKS = [
    # The HTTP to HTTPS redirect is done by nginx, before Django is reached.
    "security.W008",
    # The domain is not submitted to the browsers' HSTS preload list.
    "security.W021",
]
