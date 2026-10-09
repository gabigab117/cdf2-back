import pytest

from accounts.services.roles import is_board_member
from tests.accounts.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_members_of_the_board_group_are_board_members(board_member):
    """
    Given an account of the board group
    When its role is checked
    Then it is a board member
    """
    assert is_board_member(board_member)


def test_superusers_are_board_members():
    """
    Given a superuser outside the board group
    When their role is checked
    Then they are a board member
    """
    assert is_board_member(UserFactory(is_superuser=True))


def test_other_accounts_are_not_board_members():
    """
    Given an account that is neither a superuser nor in the board group
    When its role is checked
    Then it is not a board member
    """
    assert not is_board_member(UserFactory())
