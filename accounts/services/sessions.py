"""Sessions of the board space, each carried by a refresh token.

A session opens at sign-in and is renewed with its refresh token. Every renewal
rotates the token: a refresh token serves once, then it is blacklisted.
"""

from contextlib import suppress

from django.contrib.auth import authenticate
from django.db import transaction
from ninja_jwt.exceptions import TokenError
from ninja_jwt.settings import api_settings
from ninja_jwt.tokens import RefreshToken

from accounts.models import User
from accounts.services.roles import is_board_member


class InvalidCredentialsError(Exception):
    """The email address and the password do not match an active account."""


class InvalidSessionError(Exception):
    """The session cannot be renewed.

    Its refresh token is missing, invalid, expired or used up, or its account
    was deactivated or deleted since.
    """


class NotBoardMemberError(Exception):
    """The account is active, but it is not a board member's."""


def open_session(email: str, password: str) -> RefreshToken:
    """Sign a board member in: the refresh token of a new session."""
    # An unknown address, a wrong password and an inactive account fail alike,
    # and in the same time: the backend hashes the password even for no account.
    user = authenticate(email=email, password=password)
    if user is None:
        raise InvalidCredentialsError
    if not is_board_member(user):
        raise NotBoardMemberError
    return RefreshToken.for_user(user)


def renew_session(raw_token: str | None) -> RefreshToken:
    """Renew a session: the next refresh token, the given one being used up."""
    # RefreshToken(None) would make a brand new token instead of failing.
    if not raw_token:
        raise InvalidSessionError
    try:
        token = RefreshToken(raw_token)
    except TokenError as error:
        raise InvalidSessionError from error
    try:
        user = User.objects.get(
            **{api_settings.USER_ID_FIELD: token[api_settings.USER_ID_CLAIM]}, is_active=True
        )
    except User.DoesNotExist as error:
        raise InvalidSessionError from error
    if not is_board_member(user):
        raise NotBoardMemberError
    with transaction.atomic():
        # blacklist() returns get_or_create's pair, whatever its annotation says.
        _, created = token.blacklist()
        if not created:
            # A concurrent renewal used the token since it was verified: the
            # unique index of the blacklist lets only one of them through.
            raise InvalidSessionError
        return RefreshToken.for_user(user)


def close_session(raw_token: str | None) -> None:
    """Sign out: revoke the session's refresh token, if it is still valid."""
    if not raw_token:
        return
    with suppress(TokenError):
        RefreshToken(raw_token).blacklist()
