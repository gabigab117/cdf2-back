import pytest
from django.test import Client
from ninja_jwt.tokens import AccessToken

from tests.accounts.factories import BoardMemberFactory

# The throttles count requests in the database cache: the transaction of each
# test is rolled back, and its counts with it, so no test inherits another's.


@pytest.fixture(autouse=True)
def private_files(settings, tmp_path):
    """Every test stores its files in a folder of its own, removed after it: never
    in the repository's private/ folder.
    """
    settings.MEDIA_ROOT = tmp_path / "private"
    return settings.MEDIA_ROOT


@pytest.fixture
def board_member(db):
    return BoardMemberFactory()


@pytest.fixture
def board_client(board_member):
    """A client signed in as a board member, with a valid access token."""
    return Client(headers={"Authorization": f"Bearer {AccessToken.for_user(board_member)}"})
