import pytest

from accounts.models import User
from accounts.services.roles import BOARD_MEMBERS, is_board_member
from tests.accounts.factories import BoardMemberFactory, UserFactory

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


def test_the_board_members_condition_keeps_the_active_board_members(board_member):
    """
    Given a board member, a superuser, an account outside the board and an
    inactive board member
    When the accounts are filtered on the board members condition
    Then the board member and the superuser remain, and only them
    """
    superuser = UserFactory(is_superuser=True)
    UserFactory()
    BoardMemberFactory(is_active=False)

    assert set(User.objects.filter(BOARD_MEMBERS)) == {board_member, superuser}
