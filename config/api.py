"""The project's single NinjaAPI: every app router is mounted here."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.http import Http404
from ninja import NinjaAPI
from ninja.errors import AuthenticationError, AuthorizationError, Throttled
from ninja.errors import ValidationError as SchemaValidationError

from accounts.api import members_router
from accounts.api import router as accounts_router
from accounts.auth import BoardMemberAuth
from accounts.services.sessions import (
    InvalidCredentialsError,
    InvalidSessionError,
    NotBoardMemberError,
)
from core.api import router as core_router
from core.errors import schema_error_details, validation_error_details
from dashboard.api import router as dashboard_router
from events.api import public_router as events_public_router
from events.api import router as events_router
from notes.api import router as notes_router
from tasks.api import router as tasks_router


def serve_schema_if_enabled(view):
    """Serve the OpenAPI schema and docs only where SERVE_API_SCHEMA allows it.

    Checked on every request rather than when the URLs are built, so that the
    setting can differ between environments and be toggled in the tests.
    """

    def wrapper(request, *args, **kwargs):
        if not settings.SERVE_API_SCHEMA:
            raise Http404
        return view(request, *args, **kwargs)

    return wrapper


# Private by default: every operation is reserved to board members, unless it
# declares auth=None.
api = NinjaAPI(
    title="Comité des fêtes d'Ons-en-Bray",
    version="1.0.0",
    description="API of the Comité des fêtes d'Ons-en-Bray application.",
    auth=BoardMemberAuth(),
    docs_decorator=serve_schema_if_enabled,
)


@api.exception_handler(ValidationError)
def django_validation_error(request, exc):
    # Services raise Django's ValidationError, which Ninja does not know and
    # would turn into a 500: it becomes a 422 shaped like Ninja's own.
    return api.create_response(request, {"detail": validation_error_details(exc)}, status=422)


@api.exception_handler(SchemaValidationError)
def schema_validation_error(request, exc):
    # Ninja's own answer keeps Pydantic's messages, in English, and their
    # context, which the declared 422 schema does not hold.
    return api.create_response(request, {"detail": schema_error_details(exc)}, status=422)


@api.exception_handler(AuthenticationError)
@api.exception_handler(InvalidSessionError)
def unauthenticated(request, exc):
    return api.create_response(request, {"detail": "Authentification requise."}, status=401)


@api.exception_handler(InvalidCredentialsError)
def invalid_credentials(request, exc):
    # One answer for an unknown address, a wrong password or an inactive
    # account: it never tells which accounts exist.
    return api.create_response(request, {"detail": "Identifiants invalides."}, status=401)


@api.exception_handler(AuthorizationError)
@api.exception_handler(NotBoardMemberError)
def forbidden(request, exc):
    return api.create_response(
        request, {"detail": "Accès réservé aux membres du bureau."}, status=403
    )


@api.exception_handler(Http404)
def not_found(request, exc):
    # Ninja's own answer is in English: "Not Found".
    return api.create_response(request, {"detail": "Introuvable."}, status=404)


@api.exception_handler(Throttled)
def throttled(request, exc):
    # Ninja adds the Retry-After header to this answer.
    return api.create_response(
        request, {"detail": "Trop de requêtes. Réessayez dans quelques instants."}, status=429
    )


api.add_router("/", core_router)
api.add_router("/auth/", accounts_router)
api.add_router("/board/", events_router)
api.add_router("/board/", members_router)
api.add_router("/board/", dashboard_router)
api.add_router("/board/", notes_router)
api.add_router("/board/", tasks_router)
api.add_router("/public/", events_public_router)
