import datetime as dt
from io import StringIO

import pytest
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.core.cache import cache
from django.core.management import CommandError, call_command
from django.db import connection
from django.utils import timezone

from core.text import ERASED_NAME
from equipment.models import LoanBorrowerType, LoanStatus
from events.models import Event
from events.services.demo import DEMO_EVENTS
from events.services.periods import events_in_period
from tests.equipment.factories import LoanFactory
from tests.events.factories import EventFactory
from tests.reservations.factories import ReservationFactory
from tests.stations.factories import AssignmentFactory, StationFactory

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


def test_the_nightly_purge_erases_the_personal_data_past_its_retention():
    """
    Given a loan to a person returned a year ago today, a reservation of an
    event three months ago, and a volunteer at an event two years ago
    When `manage.py purge_personal_data` runs, as it does every night
    Then their personal data is erased
    And the command tells how many, without a name
    """
    today = timezone.localdate()

    def event_on(day):
        return EventFactory(starts_at=timezone.make_aware(dt.datetime.combine(day, dt.time(14))))

    returned = timezone.make_aware(dt.datetime.combine(today - relativedelta(years=1), dt.time(18)))
    loan = LoanFactory(
        borrower_type=LoanBorrowerType.INDIVIDUAL,
        borrower_name="M. Petit",
        phone="01 23 45 67 89",
        status=LoanStatus.RETURNED,
        returned_at=returned,
        start_date=returned.date() - dt.timedelta(days=2),
        end_date=returned.date(),
    )
    reservation = ReservationFactory(
        event=event_on(today - relativedelta(months=3)), name="Famille Martin"
    )
    volunteer = AssignmentFactory(
        station=StationFactory(event=event_on(today - relativedelta(years=2))), name="Claire"
    )
    out = StringIO()

    call_command("purge_personal_data", stdout=out)

    for erased in (loan, reservation, volunteer):
        erased.refresh_from_db()
    assert (loan.borrower_name, loan.phone) == (ERASED_NAME, "")
    assert (reservation.name, volunteer.name) == (ERASED_NAME, ERASED_NAME)
    assert out.getvalue() == (
        "Personal data erased. Phones: 1. Borrowers' names: 1. Reservations: 1. "
        "Volunteers' names: 1.\n"
    )


# The demo data of the mockup (seed_demo)


def test_the_seed_is_refused_unless_the_environment_allows_it(settings):
    """
    Given an environment that does not allow demo data, as in production
    When `manage.py seed_demo` runs
    Then it is refused, and no event is written
    """
    settings.DEMO_DATA_ENABLED = False

    with pytest.raises(CommandError, match="DEMO_DATA_ENABLED"):
        call_command("seed_demo")

    assert not Event.objects.exists()


def test_the_seed_writes_the_events_of_the_mockup_around_today(settings):
    """
    Given an environment that allows demo data
    When `manage.py seed_demo` runs
    Then the events of the mockup are written, published, five to come and four past
    And the command says how many it wrote
    """
    settings.DEMO_DATA_ENABLED = True
    out = StringIO()

    call_command("seed_demo", stdout=out)

    assert "9 demo events written." in out.getvalue()
    assert Event.objects.filter(published=True).count() == len(DEMO_EVENTS) == 9
    assert events_in_period("upcoming").count() == 5
    assert events_in_period("past").count() == 4
