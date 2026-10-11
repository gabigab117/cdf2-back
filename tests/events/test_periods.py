import datetime as dt

import pytest
from django.utils import timezone

from events.services.periods import events_in_period, events_over_by
from tests.events.factories import EventFactory

pytestmark = pytest.mark.django_db


def start_of_today():
    return timezone.make_aware(dt.datetime.combine(timezone.localdate(), dt.time.min))


def titles(period):
    return [event.title for event in events_in_period(period)]


def test_an_event_stays_upcoming_until_the_end_of_its_last_day():
    """
    Given an event of today that started at midnight in Paris, an event running
    from yesterday to tomorrow, one that ended yesterday, and one without an end
    that started yesterday
    When the events are split by period
    Then the first two are upcoming, the last two are past
    """
    today = start_of_today()
    second = dt.timedelta(seconds=1)
    EventFactory(title="Today", starts_at=today)
    EventFactory(
        title="Running",
        starts_at=today - dt.timedelta(days=1),
        ends_at=today + dt.timedelta(days=1),
    )
    EventFactory(title="Ended", starts_at=today - dt.timedelta(hours=10), ends_at=today - second)
    EventFactory(title="Started", starts_at=today - second)

    assert sorted(titles("upcoming")) == ["Running", "Today"]
    assert sorted(titles("past")) == ["Ended", "Started"]


def test_upcoming_events_come_the_next_first_and_the_others_the_latest_first():
    """
    Given events in one, two and three days, two of them at the same time, and
    events one and two days ago
    When the events are listed by period, or all together
    Then upcoming events come the next first, the first recorded first
    And past events, like the whole list, come the latest first
    """
    today = start_of_today()
    for name, days in [
        ("D+2", 2),
        ("D+1 a", 1),
        ("D+1 b", 1),
        ("D+3", 3),
        ("D-2", -2),
        ("D-1", -1),
    ]:
        EventFactory(title=name, starts_at=today + dt.timedelta(days=days))

    assert titles("upcoming") == ["D+1 a", "D+1 b", "D+2", "D+3"]
    assert titles("past") == ["D-1", "D-2"]
    assert titles(None) == ["D+3", "D+2", "D+1 b", "D+1 a", "D-1", "D-2"]


def test_an_event_is_over_by_the_end_of_its_last_day():
    """
    Given an event that ended on 15 March, one without an end that started on
    15 March at half past eleven at night, one running from 14 to 16 March, and
    one that ended at half past midnight on 16 March in Paris, still 15 March in
    UTC
    When the events over by 15 March are listed
    Then the first two are, the last two are not
    """

    def paris(day, hour, minute=0):
        return timezone.make_aware(dt.datetime(2027, 3, day, hour, minute))

    EventFactory(title="Ended", starts_at=paris(15, 14), ends_at=paris(15, 18))
    EventFactory(title="Started", starts_at=paris(15, 23, 30))
    EventFactory(title="Running", starts_at=paris(14, 10), ends_at=paris(16, 18))
    EventFactory(title="Past midnight", starts_at=paris(15, 20), ends_at=paris(16, 0, 30))

    over = events_over_by(dt.date(2027, 3, 15))

    assert sorted(event.title for event in over) == ["Ended", "Started"]
