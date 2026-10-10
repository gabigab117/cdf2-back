"""Authentication of the API: a board member's access token."""

from django.http import HttpRequest
from ninja.errors import AuthorizationError
from ninja_jwt.authentication import JWTAuth
from ninja_jwt.exceptions import AuthenticationFailed

from accounts.models import User
from accounts.services.roles import is_board_member


class BoardMemberAuth(JWTAuth):
    """Authenticates the application's single role, the board member.

    JWTAuth reads the account again on every request and refuses an inactive
    one, so deactivating an account, or taking it out of the board, takes effect
    at once. Every authentication failure (missing, invalid or expired token,
    unknown or inactive account) is reported alike, as a request without
    credentials: one 401 answer, written in config/api.py, instead of
    ninja-jwt's detailed messages.
    """

    def authenticate(self, request: HttpRequest, token: str) -> User | None:
        try:
            user = super().authenticate(request, token)
        except AuthenticationFailed:
            return None
        if not is_board_member(user):
            raise AuthorizationError
        return user


class NotSuperuserError(AuthorizationError):
    """A board member who is not the superuser, on the accounts page: its own
    403, which config/api.py words.
    """


class SuperuserAuth(BoardMemberAuth):
    """The accounts of the board (5.9): the superuser alone invites the members
    and sends them their links.
    """

    def authenticate(self, request: HttpRequest, token: str) -> User | None:
        user = super().authenticate(request, token)
        if user is not None and not user.is_superuser:
            raise NotSuperuserError
        return user
