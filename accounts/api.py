from django.conf import settings
from django.http import HttpResponse
from ninja import Cookie, Router
from ninja.pagination import paginate
from ninja.throttling import AnonRateThrottle
from ninja_jwt.tokens import RefreshToken

from accounts.schemas import AccessTokenOut, BoardMemberOut, LoginIn, MeOut
from accounts.services.roles import board_members
from accounts.services.sessions import close_session, open_session, renew_session
from core.schemas import ErrorOut, ValidationErrorOut

router = Router(tags=["auth"])

# The board's own operations on its members, mounted with the board's space.
members_router = Router(tags=["members"])

# The refresh token lives in an httpOnly cookie, out of reach of scripts, and
# goes back to the authentication endpoints only: logout needs it as well, to
# revoke it. The operations read it through a parameter of the same name.
REFRESH_COOKIE = "refresh_token"
REFRESH_COOKIE_PATH = "/api/auth/"


# One scope per throttle: AnonRateThrottle instances would otherwise share a
# single count per client IP, the renewals eating into the sign-in quota.
class LoginThrottle(AnonRateThrottle):
    scope = "login"


class RefreshThrottle(AnonRateThrottle):
    scope = "refresh"


def _set_refresh_cookie(response: HttpResponse, token: RefreshToken) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        str(token),
        max_age=token.lifetime,
        path=REFRESH_COOKIE_PATH,
        secure=settings.REFRESH_COOKIE_SECURE,
        httponly=True,
        samesite="Strict",
    )


@router.post(
    "/login",
    auth=None,
    throttle=[LoginThrottle()],
    response={
        200: AccessTokenOut,
        400: ErrorOut,
        401: ErrorOut,
        403: ErrorOut,
        422: ValidationErrorOut,
        429: ErrorOut,
    },
    summary="Sign in",
)
def login(request, response: HttpResponse, payload: LoginIn):
    """Open a session: the access token, and the refresh token in its cookie."""
    token = open_session(payload.email, payload.password)
    _set_refresh_cookie(response, token)
    return {"access": str(token.access_token)}


@router.post(
    "/refresh",
    auth=None,
    throttle=[RefreshThrottle()],
    response={200: AccessTokenOut, 401: ErrorOut, 403: ErrorOut, 429: ErrorOut},
    summary="Renew the session",
)
def refresh(request, response: HttpResponse, refresh_token: Cookie[str | None] = None):
    """Exchange the refresh cookie for a new access token and a new cookie."""
    # A refused renewal leaves the cookie alone: when two tabs renew at once,
    # the answer of the one refused would erase the fresh cookie of the other.
    token = renew_session(refresh_token)
    _set_refresh_cookie(response, token)
    return {"access": str(token.access_token)}


@router.post("/logout", auth=None, response={204: None}, summary="Sign out")
def logout(request, response: HttpResponse, refresh_token: Cookie[str | None] = None):
    """Revoke the session's refresh token and delete its cookie."""
    close_session(refresh_token)
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH, samesite="Strict")


@router.get(
    "/me",
    response={200: MeOut, 401: ErrorOut, 403: ErrorOut},
    summary="Signed-in board member",
)
def me(request):
    """The signed-in board member, as shown in the board space."""
    return request.auth


@members_router.get(
    "/members",
    response={200: list[BoardMemberOut], 401: ErrorOut, 403: ErrorOut, 422: ValidationErrorOut},
    summary="List the board members",
)
@paginate
def list_members(request):
    """The active board members, by name: the accounts that may lead an event."""
    return board_members()
