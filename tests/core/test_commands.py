from io import StringIO

import pytest
from django.conf import settings
from django.core.cache import cache
from django.core.management import call_command
from django.db import connection

pytestmark = pytest.mark.django_db


def cache_rows():
    """The rows of the database cache, the expired ones included."""
    table = connection.ops.quote_name(settings.CACHES["default"]["LOCATION"])
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        return cursor.fetchone()[0]


def test_the_nightly_purge_leaves_no_throttle_counter_behind():
    """
    Given the counter a throttle kept for an address, expired a minute ago
    And the counter of an address signing in right now
    When `manage.py clear_cache` runs, as it does every night
    Then the cache holds no row any more: no address outlives the night
    """
    cache.set("throttle_login_203.0.113.7", [1], timeout=-60)
    cache.set("throttle_login_198.51.100.4", [1], timeout=60)
    # An expired counter stays a row of its own: the database cache only
    # deletes it when it is read again.
    assert cache_rows() == 2

    call_command("clear_cache", stdout=StringIO())

    assert cache_rows() == 0
