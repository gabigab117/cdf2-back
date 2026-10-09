import pytest
from ninja_jwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from ninja_jwt.tokens import RefreshToken

from accounts.services.sessions import (
    InvalidSessionError,
    close_session,
    open_session,
    renew_session,
)
from tests.accounts.factories import PASSWORD

pytestmark = pytest.mark.django_db


def test_open_session_records_the_refresh_token(board_member):
    """
    Given a board member
    When a session is opened with their credentials
    Then its refresh token is theirs and recorded as outstanding
    """
    token = open_session(board_member.email, PASSWORD)

    assert token["user_id"] == board_member.pk
    assert OutstandingToken.objects.filter(jti=token["jti"], user=board_member).exists()


def test_renew_session_uses_up_the_given_token(board_member):
    """
    Given the refresh token of a session
    When the session is renewed
    Then the given token is blacklisted and a new one is recorded
    """
    token = RefreshToken.for_user(board_member)

    renewed = renew_session(str(token))

    assert BlacklistedToken.objects.filter(token__jti=token["jti"]).exists()
    assert OutstandingToken.objects.filter(jti=renewed["jti"], user=board_member).exists()


def test_renew_session_lets_a_token_through_only_once(board_member, monkeypatch):
    """
    Given a refresh token verified by two renewals at the same time
    When the second one blacklists it, after the first one did
    Then the second renewal is refused, and no other session opens
    """
    token = RefreshToken.for_user(board_member)
    token.blacklist()
    # Both renewals verified the token before either blacklisted it.
    monkeypatch.setattr(RefreshToken, "check_blacklist", lambda self: None)

    with pytest.raises(InvalidSessionError):
        renew_session(str(token))

    assert OutstandingToken.objects.filter(user=board_member).count() == 1


def test_close_session_blacklists_the_token(board_member):
    """
    Given the refresh token of a session
    When the session is closed
    Then the token is blacklisted
    """
    token = RefreshToken.for_user(board_member)

    close_session(str(token))

    assert BlacklistedToken.objects.filter(token__jti=token["jti"]).exists()


@pytest.mark.parametrize("raw_token", [None, ""])
def test_sessions_never_mint_a_token_from_an_empty_value(raw_token):
    """
    Given no refresh token, or an empty one
    When a session is renewed or closed with it
    Then the renewal is refused, and no token is created along the way
    """
    with pytest.raises(InvalidSessionError):
        renew_session(raw_token)
    close_session(raw_token)

    assert not OutstandingToken.objects.exists()
