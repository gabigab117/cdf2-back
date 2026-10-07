import pytest
from django.urls import reverse

from accounts.models import User

pytestmark = pytest.mark.django_db


def test_admin_creates_an_account_from_an_email(admin_client):
    """
    Given a superuser signed in to the admin
    When they add an account with an email address and a password
    Then the account exists, its email address lower-cased
    """
    response = admin_client.post(
        reverse("admin:accounts_user_add"),
        {
            "email": "Marc.D@example.fr",
            "first_name": "Marc",
            "last_name": "D.",
            "usable_password": "true",
            "password1": "a-long-password-2026",
            "password2": "a-long-password-2026",
        },
    )

    assert response.status_code == 302
    assert User.objects.filter(email="marc.d@example.fr").exists()


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
