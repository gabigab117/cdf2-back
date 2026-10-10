"""Settings shared by every environment.

Every sensitive or environment-dependent value comes from the environment (see
`.env.example`): nothing secret is written here.
"""

from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, []),
    CSRF_TRUSTED_ORIGINS=(list, []),
    ADMIN_URL=(str, "admin/"),
    STATIC_ROOT=(str, str(BASE_DIR / "staticfiles")),
    DEMO_DATA_ENABLED=(bool, False),
)
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Provides the `export_openapi_schema` command and the docs templates.
    "ninja",
    # Refresh tokens: outstanding list, blacklist and `flushexpiredtokens`.
    "ninja_jwt.token_blacklist",
    # Converts the images deposited to WebP (D9).
    "imagekit",
    "accounts",
    "core",
    "dashboard",
    "documents",
    "equipment",
    "events",
    "notes",
    "reservations",
    "stations",
    "tasks",
]

AUTH_USER_MODEL = "accounts.User"

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

# Templates only serve the Django admin: the user interface is the Nuxt front end.
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# PostgreSQL everywhere. The connection is assembled from separate variables
# rather than a DATABASE_URL: no second source of truth, and no URL-encoding of
# special characters in the password. An empty host means the local Unix socket
# (peer authentication on the server, no password at all).
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB"),
        "USER": env("POSTGRES_USER"),
        "PASSWORD": env("POSTGRES_PASSWORD", default=""),
        "HOST": env("POSTGRES_HOST", default=""),
        "PORT": env("POSTGRES_PORT", default=""),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# French conventions: stored in UTC, displayed in Paris time by the front end.
LANGUAGE_CODE = "fr-fr"
TIME_ZONE = "Europe/Paris"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = Path(env("STATIC_ROOT"))

# The private files (A8): outside the web root, never served by a URL of their
# own, only by the API once it has checked who asks. The repository's private/
# folder by default; on the server, shared/private, required there.
MEDIA_ROOT = Path(env("MEDIA_ROOT", default=str(BASE_DIR / "private")))

# The largest file a member may deposit, in bytes: below the 20 MB nginx
# accepts, so that the API, rather than nginx, tells the member.
DOCUMENT_MAX_SIZE = env.int("DOCUMENT_MAX_SIZE", default=15 * 1024 * 1024)

# Where nginx serves the private files from, once the API has checked the
# access (X-Accel-Redirect). None: Django sends them itself, as in development.
PRIVATE_FILES_ACCEL_PREFIX = None

# The address of the site, for the links of the emails: the API never learns
# the front end's from a request. Required on the server.
SITE_URL = env("SITE_URL", default="http://localhost:3000")

# The emails of the application (D7, D8). The console shows them in
# development, and the tests replace every mailer with an outbox in memory;
# the server sends them through the association's SMTP (prod.py). No EMAIL_*
# setting: they are deprecated by MAILERS, which refuses to mix with them.
MAILERS = {
    "default": {"BACKEND": "django.core.mail.backends.console.EmailBackend"},
}
# The sender: the address of the account the emails go through. Required on the server.
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="Comité des fêtes <comite@example.org>")

# The application's journal (A9: 7 days on the server, by systemd): what the
# project's loggers report goes to the error stream. Django's own loggers are
# left as they are.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"journal": {"class": "logging.StreamHandler"}},
    "loggers": {"documents": {"handlers": ["journal"], "level": "WARNING"}},
}

# The admin is moved off its well-known path by the environment.
ADMIN_URL = env("ADMIN_URL")

# The OpenAPI schema and the interactive docs are only served where the front
# end needs them (development, tests). An explicit setting rather than DEBUG,
# which the test suite always forces to False.
SERVE_API_SCHEMA = False

# `manage.py seed_demo` writes the fictitious events of the mockup. It is
# allowed by the environment alone, development and preproduction, and refused
# elsewhere. No settings file turns it on: on a server, manage.py run without
# DJANGO_SETTINGS_MODULE loads the development settings.
DEMO_DATA_ENABLED = env("DEMO_DATA_ENABLED")

# Every collection of resources is paginated by page number (see CLAUDE.md).
NINJA_PAGINATION_CLASS = "ninja.pagination.PageNumberPagination"
NINJA_PAGINATION_PER_PAGE = 25

# Authentication (accounts/api.py): a short-lived access token sent in the
# Authorization header, and a refresh token kept in an httpOnly cookie, both
# signed with SECRET_KEY. Every renewal rotates the refresh token and
# blacklists the old one (accounts/services/sessions.py): ninja-jwt's
# ROTATE_REFRESH_TOKENS and BLACKLIST_AFTER_ROTATION only drive its own
# controllers, which this API does not use.
NINJA_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
}

# The refresh cookie only travels over HTTPS, except on the local dev server.
REFRESH_COOKIE_SECURE = True

# Strict throttling of the authentication endpoints, per client IP. The rates
# are read once, when the API is imported.
NINJA_DEFAULT_THROTTLE_RATES = {
    "login": "5/min",
    "refresh": "20/min",
}

# The throttles count requests in the cache, which every gunicorn worker must
# share: a table of the database (`manage.py createcachetable`).
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "django_cache",
    }
}

# A deployed release carries a REVISION file holding its git SHA, written by the
# deployment script. The health check reports it, so a deployment can verify
# that the expected code is the one actually answering.
_revision_file = BASE_DIR / "REVISION"
RELEASE_SHA = _revision_file.read_text().strip() if _revision_file.exists() else "dev"
