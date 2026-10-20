import datetime as dt

import pytest
from django.utils import timezone

from tests.accounts.factories import BoardMemberFactory, client_of

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
    return client_of(board_member)


@pytest.fixture
def mockup_day(monkeypatch):
    """Today is the mockup's day, Thursday 1 October 2026, in Paris."""
    monkeypatch.setattr(timezone, "localdate", lambda *args, **kwargs: dt.date(2026, 10, 1))
