"""The application's single role: board member (decision A2 of the roadmap)."""

from django.db.models import Q

from accounts.models import User

# Members of this group, and superusers, are board members. The group is
# created by a migration (accounts/migrations/0003_board_group.py).
BOARD_GROUP = "Bureau"

# The same rule as a query condition, to choose among the accounts (the lead of
# an event). Unlike is_board_member(), only asked about an account already
# authenticated, it leaves the inactive accounts out.
BOARD_MEMBERS = Q(is_active=True) & (Q(is_superuser=True) | Q(groups__name=BOARD_GROUP))


def is_board_member(user: User) -> bool:
    """Tell whether an account may use the board space and the private API.

    Whether the account is active is checked before, when it is authenticated:
    an inactive account is not authenticated at all (401), while an active one
    outside the board is authenticated, then refused (403).
    """
    return user.is_superuser or user.groups.filter(name=BOARD_GROUP).exists()
