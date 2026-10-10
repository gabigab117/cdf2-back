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

# The links of the emails, and their sender: no default on the server.
SITE_URL = env("SITE_URL")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL")

# Server errors (status 500 and above) are emailed to the administrators by
# Django's own handler, which LOGGING keeps, through the same mailer and from
# the same sender: the SMTP refuses root@localhost. Nobody is emailed while the
# list is empty, as on the preproduction.
ADMINS = env.list("ADMINS", default=[])
SERVER_EMAIL = DEFAULT_FROM_EMAIL

# The emails go through the SMTP of the association's account (D7): implicit
# SSL, on port 465 by default. The timeout is short: an email is sent during
# the request of the deposit, which must not wait long on it.
MAILERS = {
    "default": {
        "BACKEND": "django.core.mail.backends.smtp.EmailBackend",
        "OPTIONS": {
            "host": env("MAILER_HOST"),
            "use_ssl": True,
            "username": env("MAILER_USERNAME"),
            "password": env("MAILER_PASSWORD"),
            "timeout": 10,
        },
    },
}

SILENCED_SYSTEM_CHECKS = [
    # The HTTP to HTTPS redirect is done by nginx, before Django is reached.
    "security.W008",
    # The domain is not submitted to the browsers' HSTS preload list.
    "security.W021",
]
