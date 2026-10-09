import datetime as dt

import pytest
from django.utils import timezone

from events.models import Event, EventCategory
from events.services.agenda import agenda_categories, agenda_updated_at, next_events
from tests.events.factories import EventFactory

pytestmark = pytest.mark.django_db


def in_days(days, hour=15):
    """A time in Paris, some days from today."""
    day = timezone.localdate() + dt.timedelta(days=days)
    return timezone.make_aware(dt.datetime.combine(day, dt.time(hour)))


def published(title, days, **fields):
    return EventFactory(title=title, starts_at=in_days(days), published=True, **fields)


def titles(events):
    return [event.title for event in events]


# Categories


def test_the_agenda_offers_its_categories_once_each_in_their_usual_order():
    """
    Given two games and a children's event to come, a meal still a draft, and a
    past market
    When the categories of the agenda are listed
    Then the children's events come before the games, each once, and neither
    the draft's nor the past event's category is offered
    """
    published("Loto", 10, category=EventCategory.GAMES)
    published("Halloween", 5, category=EventCategory.CHILDREN)
    published("Belote", 20, category=EventCategory.GAMES)
    EventFactory(title="Repas", starts_at=in_days(3), category=EventCategory.MEALS)
    published("Marché", -30, category=EventCategory.MARKETS)

    assert agenda_categories() == [EventCategory.CHILDREN, EventCategory.GAMES]


# Last change


def test_the_agenda_changed_last_when_its_latest_changed_event_did():
    """
    Given two published events to come, changed three days and one day ago, a
    draft and a past event changed today
    When the agenda's last change is asked
    Then it is the day before: neither the draft nor the past event counts
    """
    now = timezone.now()
    changes = {
        published("Loto", 10): now - dt.timedelta(days=3),
        published("Halloween", 5): now - dt.timedelta(days=1),
        EventFactory(title="Repas", starts_at=in_days(3)): now,
        published("Marché", -30): now,
    }
    # update() leaves auto_now aside, which save() would apply.
    for event, updated_at in changes.items():
        Event.objects.filter(pk=event.pk).update(updated_at=updated_at)

    assert agenda_updated_at() == now - dt.timedelta(days=1)


def test_an_empty_agenda_has_no_last_change():
    """
    Given no published event to come, only a draft
    When the agenda's last change is asked
    Then there is none
    """
    EventFactory()

    assert agenda_updated_at() is None


# Next events


def test_an_event_is_followed_by_the_two_next_events_of_the_agenda():
    """
    Given four published events to come and a draft among them
    When the events that follow each of them are asked
    Then each is followed by the next two at most, the draft never, and the
    last by none
    """
    first = published("First", 1)
    published("Second", 2)
    EventFactory(title="Draft", starts_at=in_days(2, hour=18))
    third = published("Third", 3)
    last = published("Last", 4)

    assert titles(next_events(first)) == ["Second", "Third"]
    assert titles(next_events(third)) == ["Last"]
    assert next_events(last) == []


def test_events_starting_together_follow_one_another_in_their_recording_order():
    """
    Given two published events starting at the same time, recorded one after
    the other, and a published event the day after
    When the events that follow each of the first two are asked
    Then the first recorded is followed by the second, which is not followed by
    the first
    """
    recorded_first = published("Recorded first", 2)
    recorded_second = published("Recorded second", 2)
    published("Day after", 3)

    assert titles(next_events(recorded_first)) == ["Recorded second", "Day after"]
    assert titles(next_events(recorded_second)) == ["Day after"]


def test_a_past_event_is_followed_by_the_first_events_of_the_agenda():
    """
    Given published events of last month and of last week, and three to come
    When the events that follow last month's are asked
    Then they are the first two of the agenda: last week's is over
    """
    past = published("Last month", -30)
    published("Last week", -7)
    published("Soon", 2)
    published("Later", 5)
    published("Much later", 9)

    assert titles(next_events(past)) == ["Soon", "Later"]
