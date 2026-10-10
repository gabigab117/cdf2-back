import pytest
from django.contrib import admin
from django.contrib.auth.models import Group
from django.urls import reverse
from ninja_jwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from accounts.models import BoardPosition, User
from accounts.services.roles import BOARD_GROUP, is_board_member

pytestmark = pytest.mark.django_db


def test_admin_creates_a_board_member_account(admin_client):
    """
    Given a superuser signed in to the admin
    When they add an account with an email address, a position, the board group
    and a password
    Then the account exists, its email address lower-cased
    And it is a board member from the start
    """
    response = admin_client.post(
        reverse("admin:accounts_user_add"),
        {
            "email": "Marc.D@example.fr",
            "first_name": "Marc",
            "last_name": "D.",
            "position": "secretary",
            "groups": [Group.objects.get(name=BOARD_GROUP).pk],
            "usable_password": "true",
            "password1": "a-long-password-2026",
            "password2": "a-long-password-2026",
        },
    )

    assert response.status_code == 302
    user = User.objects.get(email="marc.d@example.fr")
    assert user.position == BoardPosition.SECRETARY
    assert is_board_member(user)


def test_admin_lists_searches_and_edits_accounts(admin_client, admin_user):
    """
    Given a superuser signed in to the admin
    When they search the accounts and open their own
    Then both pages are displayed
    """
    changelist = admin_client.get(reverse("admin:accounts_user_changelist"), {"q": "admin"})
    change = admin_client.get(reverse("admin:accounts_user_change", args=[admin_user.pk]))

    assert changelist.status_code == 200
    assert change.status_code == 200


def test_admin_does_not_show_the_refresh_tokens():
    """
    Given the token blacklist of the authentication
    When the admin pages are listed
    Then none shows the tokens, which would let their reader act as their owners
    """
    assert not admin.site.is_registered(OutstandingToken)
    assert not admin.site.is_registered(BlacklistedToken)
