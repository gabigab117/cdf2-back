import datetime as dt

import pytest
from django.utils import timezone

from core.text import ERASED_NAME
from reservations.services.purge import purge_reservations
from reservations.services.reservations import reservation_stats
from tests.events.factories import EventFactory
from tests.reservations.factories import TicketTypeFactory, reserve

pytestmark = pytest.mark.django_db

# Three months before it is a day of its own: no month end moves the boundary.
TODAY = dt.date(2027, 6, 15)


def event_on(day):
    """An afternoon event on a day, in Paris."""
    return EventFactory(
        starts_at=timezone.make_aware(dt.datetime.combine(day, dt.time(14))),
        ends_at=timezone.make_aware(dt.datetime.combine(day, dt.time(18))),
    )


def booked(event):
    """A reservation of two places, with a remark."""
    menu = TicketTypeFactory(event=event, name="Menu adulte")
    return reserve(event, name="Famille Martin", note="Près de la scène", adulte=(menu, 2))


def totals(event):
    stats = reservation_stats(event)
    by_type = [(ticket_type.name, ticket_type.seats) for ticket_type in stats.ticket_types]
    return stats.reservations, stats.seats, by_type


def test_a_reservations_name_and_remark_are_erased_three_months_after_its_event():
    """
    Given a reservation of an event of 15 March, and one of an event of 16 March
    When the purge runs on 15 June
    Then the first is « Nom effacé », without its remark
    And the second keeps its name and its remark until the next night
    """
    over = booked(event_on(dt.date(2027, 3, 15)))
    kept = booked(event_on(dt.date(2027, 3, 16)))

    erased = purge_reservations(TODAY)

    over.refresh_from_db()
    kept.refresh_from_db()
    assert (over.name, over.note) == (ERASED_NAME, "")
    assert (kept.name, kept.note) == ("Famille Martin", "Près de la scène")
    assert erased == 1


def test_an_event_keeps_its_totals():
    """
    Given an event of a year ago, with a reservation of two adult menus
    When the purge erases the reservation's name
    Then the event still counts one reservation and two places, by type
    """
    event = event_on(dt.date(2026, 6, 1))
    booked(event)
    before = totals(event)

    purge_reservations(TODAY)

    assert totals(event) == before == (1, 2, [("Menu adulte", 2)])


def test_the_purge_counts_only_what_it_erases():
    """
    Given a reservation of an event of a year ago
    When the purge runs, then again the next night
    Then the first counts it, the second nothing
    """
    booked(event_on(dt.date(2026, 6, 1)))

    assert purge_reservations(TODAY) == 1
    assert purge_reservations(TODAY) == 0
