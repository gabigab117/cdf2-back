import pytest
from django.contrib.auth.models import Group

from accounts.models import User
from accounts.services.roles import BOARD_MEMBERS, board_members, is_board_member
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


def test_the_board_members_come_by_name_then_by_email_address():
    """
    Given board members created in no particular order, two of them namesakes
    When the board members are listed
    Then they come by first name and last name, the namesakes by email address
    """
    julie = BoardMemberFactory(first_name="Julie", last_name="Roux")
    second = BoardMemberFactory(email="camille.b@example.fr")
    alain = BoardMemberFactory(first_name="Alain", last_name="Petit")
    first = BoardMemberFactory(email="camille.a@example.fr")

    assert list(board_members()) == [alain, first, second, julie]


def test_a_superuser_in_several_groups_is_listed_once():
    """
    Given a superuser who belongs to the board group and to another group
    When the board members are listed
    Then they appear once, although the join on the groups finds them twice
    """
    superuser = BoardMemberFactory(is_superuser=True)
    superuser.groups.add(Group.objects.create(name="Animations"))

    assert list(board_members()) == [superuser]
