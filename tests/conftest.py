import pytest
from django.test import Client
from ninja_jwt.tokens import AccessToken

from tests.accounts.factories import BoardMemberFactory

# The throttles count requests in the database cache: the transaction of each
# test is rolled back, and its counts with it, so no test inherits another's.


@pytest.fixture
def board_member(db):
    return BoardMemberFactory()


@pytest.fixture
def board_client(board_member):
    """A client signed in as a board member, with a valid access token."""
    return Client(headers={"Authorization": f"Bearer {AccessToken.for_user(board_member)}"})
