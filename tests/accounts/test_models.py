import pytest
from django.core.exceptions import ValidationError
from django.db import connection

from accounts.models import User

pytestmark = pytest.mark.django_db


def test_create_user_stores_a_lower_cased_email():
    """
    Given an email address typed with capital letters
    When a user is created with it
    Then the address is stored lower-cased
    And the user is a plain account, without any position, who signs in with
    the given password
    """
    user = User.objects.create_user(email="Julie.R@Example.FR", password="a-long-password")

    assert user.email == "julie.r@example.fr"
    assert user.check_password("a-long-password")
    assert not user.is_staff
    assert not user.is_superuser
    assert user.position == ""


def test_create_user_requires_an_email():
    """
    Given no email address
    When a user is created
    Then the creation is refused
    """
    with pytest.raises(ValueError, match="email address is required"):
        User.objects.create_user(email="", password="a-long-password")


def test_create_superuser_grants_the_admin_rights():
    """
    Given an email address and a password
    When a superuser is created
    Then the account is staff and superuser
    """
    user = User.objects.create_superuser(email="admin@example.fr", password="a-long-password")

    assert user.is_staff
    assert user.is_superuser


@pytest.mark.parametrize("flag", ["is_staff", "is_superuser"])
def test_create_superuser_refuses_to_drop_an_admin_right(flag):
    """
    Given a superuser creation that sets one of its admin rights to False
    When the superuser is created
    Then the creation is refused
    """
    with pytest.raises(ValueError, match=f"{flag}=True"):
        User.objects.create_superuser(
            email="admin@example.fr", password="a-long-password", **{flag: False}
        )


def test_email_is_unique_whatever_its_case():
    """
    Given an account for julie@example.fr
    When another account is validated with JULIE@example.fr
    Then the validation reports the email address as already used
    """
    User.objects.create_user(email="julie@example.fr", password="a-long-password")
    other = User(email="JULIE@example.fr")
    other.set_password("a-long-password")

    with pytest.raises(ValidationError) as error:
        other.full_clean()

    assert "email" in error.value.message_dict


def test_accounts_are_found_whatever_the_case_of_the_address():
    """
    Given an account for julie.r@example.fr
    When it is looked up as Julie.R@Example.FR, as on sign-in
    Then the account is found
    """
    user = User.objects.create_user(email="julie.r@example.fr", password="a-long-password")

    assert User.objects.get_by_natural_key("Julie.R@Example.FR") == user


def test_the_previous_release_can_still_create_accounts():
    """
    Given the position column, unknown to the code of the previous release
    When an account is inserted without it, as that release does
    Then the database gives it an empty position
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO accounts_user (password, is_superuser, first_name, last_name,"
            " is_staff, is_active, date_joined, email)"
            " VALUES ('!', false, '', '', false, true, now(), 'former@example.fr')"
        )

    assert User.objects.get(email="former@example.fr").position == ""
