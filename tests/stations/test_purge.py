import datetime as dt

import pytest
from django.utils import timezone

from core.text import ERASED_NAME
from stations.services.purge import purge_volunteers
from stations.services.stations import station_board
from tests.events.factories import EventFactory
from tests.stations.factories import AssignmentFactory, StationFactory

pytestmark = pytest.mark.django_db

# Two years before it is a day of its own: no month end moves the boundary.
TODAY = dt.date(2027, 6, 15)


def staffed(day):
    """A station of an event on a day, in Paris, with a volunteer and their role."""
    event = EventFactory(
        starts_at=timezone.make_aware(dt.datetime.combine(day, dt.time(14))),
        ends_at=timezone.make_aware(dt.datetime.combine(day, dt.time(18))),
    )
    station = StationFactory(event=event, name="Buvette", required_count=2)
    return AssignmentFactory(station=station, name="Claire", role="Bière uniquement")


def test_a_volunteers_name_is_erased_two_years_after_the_event():
    """
    Given a volunteer at an event of 15 June two years ago, and one at an event
    of 16 June
    When the purge runs on 15 June
    Then the first is « Nom effacé », their role kept
    And the second keeps their name until the next night
    """
    over = staffed(dt.date(2025, 6, 15))
    kept = staffed(dt.date(2025, 6, 16))

    erased = purge_volunteers(TODAY)

    over.refresh_from_db()
    kept.refresh_from_db()
    assert (over.name, over.role) == (ERASED_NAME, "Bière uniquement")
    assert kept.name == "Claire"
    assert erased == 1


def test_the_stations_keep_their_people():
    """
    Given a station of an event of three years ago, one person at it out of two
    When the purge erases their name
    Then the station still counts one person out of two
    """
    event = staffed(dt.date(2024, 6, 1)).station.event

    purge_volunteers(TODAY)

    board = station_board(event)
    assert (board.assigned_count, board.required_count, board.open_places) == (1, 2, 1)


def test_the_purge_counts_only_what_it_erases():
    """
    Given a volunteer at an event of three years ago
    When the purge runs, then again the next night
    Then the first counts them, the second nothing
    """
    staffed(dt.date(2024, 6, 1))

    assert purge_volunteers(TODAY) == 1
    assert purge_volunteers(TODAY) == 0
