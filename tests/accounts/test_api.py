from datetime import timedelta

import pytest
from django.urls import reverse
from ninja_jwt.token_blacklist.models import BlacklistedToken
from ninja_jwt.tokens import AccessToken, RefreshToken

from accounts.api import REFRESH_COOKIE, REFRESH_COOKIE_PATH
from tests.accounts.factories import PASSWORD, BoardMemberFactory, UserFactory

pytestmark = pytest.mark.django_db

LOGIN = "/api/auth/login"
REFRESH = "/api/auth/refresh"
LOGOUT = "/api/auth/logout"
ME = "/api/auth/me"

UNAUTHENTICATED = {"detail": "Authentification requise."}
FORBIDDEN = {"detail": "Accès réservé aux membres du bureau."}


def login(client, email, password=PASSWORD):
    return client.post(
        LOGIN, {"email": email, "password": password}, content_type="application/json"
    )


def expired(token):
    token.set_exp(lifetime=-timedelta(seconds=1))
    return str(token)


# Sign in


def test_login_opens_a_session(client, board_member):
    """
    Given a board member
    When they sign in with their email address and password
    Then the answer holds an access token of theirs, valid for 15 minutes
    And the refresh token of the session is set in its cookie
    """
    response = login(client, board_member.email)

    assert response.status_code == 200
    access = AccessToken(response.json()["access"])
    assert access["user_id"] == board_member.pk
    assert access["exp"] - access["iat"] == 15 * 60
    assert RefreshToken(response.cookies[REFRESH_COOKIE].value)["user_id"] == board_member.pk


def test_login_sets_a_cookie_out_of_reach_of_scripts(client, board_member):
    """
    Given a board member signing in
    When the refresh cookie is set
    Then it is httpOnly, Secure, SameSite=Strict, limited to the authentication
    endpoints and kept as long as the refresh token, 7 days
    """
    cookie = login(client, board_member.email).cookies[REFRESH_COOKIE]

    assert cookie["httponly"] is True
    assert cookie["secure"] is True
    assert cookie["samesite"] == "Strict"
    assert cookie["path"] == "/api/auth/"
    assert cookie["max-age"] == 7 * 24 * 3600


def test_login_ignores_the_case_and_surrounding_spaces_of_the_email(client):
    """
    Given a board member whose address is julie.r@example.fr
    When they sign in typing " Julie.R@Example.FR "
    Then they are signed in
    """
    BoardMemberFactory(email="julie.r@example.fr")

    assert login(client, " Julie.R@Example.FR ").status_code == 200


def test_login_checks_the_password_exactly_as_typed(client):
    """
    Given a board member whose password begins and ends with spaces
    When they sign in with it, then without its spaces
    Then only the password typed in full is accepted
    """
    member = BoardMemberFactory(password="  spaced password  ")

    assert login(client, member.email, "  spaced password  ").status_code == 200
    assert login(client, member.email, "spaced password").status_code == 401


@pytest.mark.parametrize(
    ("account", "email", "password"),
    [
        ({}, None, "not-the-password"),
        ({}, "nobody@example.fr", PASSWORD),
        ({"is_active": False}, None, PASSWORD),
    ],
    ids=["wrong password", "unknown email", "inactive account"],
)
def test_login_refuses_wrong_credentials_alike(client, account, email, password):
    """
    Given a wrong password, an unknown address or an inactive account
    When someone signs in with it
    Then the answer is the same 401 in every case, without any cookie
    """
    member = BoardMemberFactory(**account)

    response = login(client, email or member.email, password)

    assert response.status_code == 401
    assert response.json() == {"detail": "Identifiants invalides."}
    assert REFRESH_COOKIE not in response.cookies


def test_login_refuses_an_account_outside_the_board(client):
    """
    Given an active account outside the board group
    When it signs in with the right password
    Then the answer is a 403, without any cookie
    """
    account = UserFactory()

    response = login(client, account.email)

    assert response.status_code == 403
    assert response.json() == FORBIDDEN
    assert REFRESH_COOKIE not in response.cookies


def test_login_lets_a_superuser_in_without_the_board_group(client):
    """
    Given a superuser outside the board group
    When they sign in
    Then they are signed in, as a board member
    """
    superuser = UserFactory(is_superuser=True)

    assert login(client, superuser.email).status_code == 200


def test_login_reports_a_missing_field(client):
    """
    Given a sign-in without any password
    When it is sent
    Then the answer is a 422 locating the missing field
    """
    response = client.post(LOGIN, {"email": "julie@example.fr"}, content_type="application/json")

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"][-1] == "password"


def test_login_rejects_a_body_that_is_not_json(client):
    """
    Given a sign-in whose body is not valid JSON
    When it is sent
    Then the answer is a 400
    """
    response = client.post(LOGIN, "{not json", content_type="application/json")

    assert response.status_code == 400


def test_login_is_throttled_after_five_attempts(client, board_member):
    """
    Given five sign-in attempts from the same address within a minute
    When a sixth one is made, even with the right password
    Then it is refused with a 429 telling how long to wait
    """
    for _ in range(5):
        assert login(client, board_member.email, "not-the-password").status_code == 401

    response = login(client, board_member.email)

    assert response.status_code == 429
    assert response.json() == {"detail": "Trop de requêtes. Réessayez dans quelques instants."}
    assert int(response["Retry-After"]) > 0


def test_renewals_do_not_use_up_the_sign_in_quota(client, board_member):
    """
    Given five session renewals from an address within a minute
    When a board member signs in from the same address
    Then they are signed in: each endpoint counts its own requests
    """
    for _ in range(5):
        client.post(REFRESH)

    assert login(client, board_member.email).status_code == 200


# Session renewal


def test_refresh_rotates_the_refresh_token(client, board_member):
    """
    Given a signed-in board member
    When they renew their session
    Then they get a new access token and a new refresh cookie
    And the previous refresh token is refused from then on
    """
    first = login(client, board_member.email).cookies[REFRESH_COOKIE].value

    response = client.post(REFRESH)

    assert response.status_code == 200
    assert AccessToken(response.json()["access"])["user_id"] == board_member.pk
    second = response.cookies[REFRESH_COOKIE].value
    assert second != first
    client.cookies[REFRESH_COOKIE] = first
    assert client.post(REFRESH).status_code == 401
    client.cookies[REFRESH_COOKIE] = second
    assert client.post(REFRESH).status_code == 200


def test_refresh_requires_a_cookie(client):
    """
    Given no refresh cookie
    When a renewal is requested
    Then it is refused with a 401
    """
    response = client.post(REFRESH)

    assert response.status_code == 401
    assert response.json() == UNAUTHENTICATED


@pytest.mark.parametrize(
    "cookie_for",
    [
        lambda member: "",
        lambda member: "not-a-token",
        lambda member: expired(RefreshToken.for_user(member)),
        lambda member: str(AccessToken.for_user(member)),
    ],
    ids=["empty", "garbage", "expired", "access token"],
)
def test_refresh_refuses_an_invalid_cookie(client, board_member, cookie_for):
    """
    Given a refresh cookie that is empty, unreadable, expired or of another kind
    When a renewal is requested with it
    Then it is refused with a 401
    """
    client.cookies[REFRESH_COOKIE] = cookie_for(board_member)

    response = client.post(REFRESH)

    assert response.status_code == 401
    assert response.json() == UNAUTHENTICATED


def test_refresh_after_logout_is_refused(client, board_member):
    """
    Given a board member who signed out
    When someone renews the session with a copy of its refresh token
    Then it is refused with a 401
    """
    token = login(client, board_member.email).cookies[REFRESH_COOKIE].value
    client.post(LOGOUT)
    # The test client keeps the emptied cookie: the copy is put back on purpose.
    client.cookies[REFRESH_COOKIE] = token

    assert client.post(REFRESH).status_code == 401


def test_refresh_refuses_a_deactivated_account(client, board_member):
    """
    Given a signed-in board member whose account is then deactivated
    When the session is renewed
    Then it is refused with a 401
    """
    login(client, board_member.email)
    board_member.is_active = False
    board_member.save()

    assert client.post(REFRESH).status_code == 401


def test_refresh_refuses_an_account_taken_out_of_the_board(client, board_member):
    """
    Given a signed-in board member who is then taken out of the board group
    When the session is renewed
    Then it is refused with a 403
    """
    login(client, board_member.email)
    board_member.groups.clear()

    response = client.post(REFRESH)

    assert response.status_code == 403
    assert response.json() == FORBIDDEN


def test_refresh_is_throttled_after_twenty_requests(client):
    """
    Given twenty renewal requests from the same address within a minute
    When a twenty-first one is made
    Then it is refused with a 429
    """
    for _ in range(20):
        assert client.post(REFRESH).status_code == 401

    assert client.post(REFRESH).status_code == 429


# Sign out


def test_logout_revokes_the_refresh_token_and_deletes_its_cookie(client, board_member):
    """
    Given a signed-in board member
    When they sign out
    Then their refresh token is blacklisted
    And the cookie is deleted, on the path it was set on
    """
    token = login(client, board_member.email).cookies[REFRESH_COOKIE].value

    response = client.post(LOGOUT)

    assert response.status_code == 204
    assert response.content == b""
    cookie = response.cookies[REFRESH_COOKIE]
    assert cookie.value == ""
    assert cookie["max-age"] == 0
    assert cookie["path"] == REFRESH_COOKIE_PATH
    assert cookie["samesite"] == "Strict"
    assert BlacklistedToken.objects.filter(token__token=token).exists()


@pytest.mark.parametrize("cookies", [{}, {REFRESH_COOKIE: "not-a-token"}], ids=["none", "garbage"])
def test_logout_succeeds_without_a_valid_session(client, cookies):
    """
    Given no refresh cookie, or an unreadable one
    When someone signs out
    Then the answer is still a 204: there is nothing left to revoke
    """
    client.cookies.load(cookies)

    assert client.post(LOGOUT).status_code == 204


def test_the_refresh_cookie_reaches_the_endpoints_that_read_it():
    """
    Given the path the refresh cookie is limited to
    When it is compared with the URLs of the renewal and of the sign-out
    Then both lie under it, so that browsers send them the cookie
    """
    assert reverse("api-1.0.0:refresh").startswith(REFRESH_COOKIE_PATH)
    assert reverse("api-1.0.0:logout").startswith(REFRESH_COOKIE_PATH)


# Signed-in board member


def test_me_describes_the_signed_in_board_member(board_client, board_member):
    """
    Given a signed-in board member
    When they ask who they are
    Then the answer gives their email address, names and position
    """
    response = board_client.get(ME)

    assert response.status_code == 200
    assert response.json() == {
        "email": board_member.email,
        "first_name": "Camille",
        "last_name": "Martin",
        "position": "Trésorière",
    }


@pytest.mark.parametrize(
    "headers_for",
    [
        lambda member: {},
        lambda member: {"Authorization": "Bearer not-a-token"},
        lambda member: {"Authorization": f"Bearer {expired(AccessToken.for_user(member))}"},
        lambda member: {"Authorization": f"Bearer {RefreshToken.for_user(member)}"},
    ],
    ids=["no token", "garbage", "expired", "refresh token"],
)
def test_private_operations_require_a_valid_access_token(client, board_member, headers_for):
    """
    Given a request without an access token, or with an invalid, expired or
    wrong kind of token
    When it reaches a private operation
    Then it is refused with a 401
    """
    response = client.get(ME, headers=headers_for(board_member))

    assert response.status_code == 401
    assert response.json() == UNAUTHENTICATED


def test_a_deactivated_account_is_refused_at_once(board_client, board_member):
    """
    Given a board member holding a valid access token
    When their account is deactivated
    Then their next request is refused with a 401, without waiting for the token
    to expire
    """
    board_member.is_active = False
    board_member.save()

    assert board_client.get(ME).status_code == 401


def test_an_account_taken_out_of_the_board_is_refused_at_once(board_client, board_member):
    """
    Given a board member holding a valid access token
    When they are taken out of the board group
    Then their next request is refused with a 403
    """
    board_member.groups.clear()

    response = board_client.get(ME)

    assert response.status_code == 403
    assert response.json() == FORBIDDEN
