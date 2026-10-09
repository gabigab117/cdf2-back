import datetime as dt

import pytest
from icalendar import Calendar

from events.models import Event
from events.services.calendar import agenda_calendar, event_calendar
from tests.events.factories import EventFactory

pytestmark = pytest.mark.django_db

SITE = "https://example.org/"


def entries(content):
    return Calendar.from_ical(content).events


def test_an_event_is_written_in_paris_time_in_winter_and_in_summer():
    """
    Given an event on 31 October at 14:00 UTC, until 17:30 UTC, and another on
    21 June at 18:00 UTC
    When the agenda is written as a calendar
    Then their times are those of Paris, an hour ahead in winter and two in
    summer, and the calendar defines Paris time
    """
    EventFactory(
        title="Halloween",
        starts_at=dt.datetime(2026, 10, 31, 14, tzinfo=dt.UTC),
        ends_at=dt.datetime(2026, 10, 31, 17, 30, tzinfo=dt.UTC),
    )
    EventFactory(title="Fête de la musique", starts_at=dt.datetime(2026, 6, 21, 18, tzinfo=dt.UTC))

    content = agenda_calendar(Event.objects.order_by("starts_at"), SITE)

    lines = content.decode().splitlines()
    assert "DTSTART;TZID=Europe/Paris:20261031T150000" in lines
    assert "DTEND;TZID=Europe/Paris:20261031T183000" in lines
    assert "DTSTART;TZID=Europe/Paris:20260621T200000" in lines
    assert [zone.tz_name for zone in Calendar.from_ical(content).timezones] == ["Europe/Paris"]


def test_an_event_without_an_end_has_none_in_the_calendar():
    """
    Given an event with a start and no end
    When it is written as a calendar file
    Then its entry has no end: calendars show it at its start
    """
    event = EventFactory(ends_at=None)

    (entry,) = entries(event_calendar(event, SITE))

    assert "DTEND" not in entry
    assert "DURATION" not in entry


def test_an_entry_holds_what_a_calendar_shows_of_its_event():
    """
    Given an event with a venue address and a summary
    When it is written as a calendar file
    Then its entry holds its title, its venue then address, its summary then
    the link to its page, the link itself, an id made of its own and the site's,
    and the time it last changed
    """
    event = EventFactory(
        title="Halloween des enfants",
        slug="halloween-des-enfants-2026",
        venue_name="Salle des fêtes",
        venue_address="1 place de la Mairie",
        summary="Défilé costumé, puis goûter.",
    )

    (entry,) = entries(event_calendar(event, SITE))

    page = "https://example.org/evenements/halloween-des-enfants-2026"
    assert entry["SUMMARY"] == "Halloween des enfants"
    assert entry["LOCATION"] == "Salle des fêtes, 1 place de la Mairie"
    assert entry["DESCRIPTION"] == f"Défilé costumé, puis goûter.\n\n{page}"
    assert entry["URL"] == page
    assert entry["UID"] == f"event-{event.pk}@example.org"
    # iCalendar writes times to the second.
    assert entry.stamp == entry.last_modified == event.updated_at.replace(microsecond=0)


def test_an_entry_without_address_or_summary_keeps_the_venue_and_the_link():
    """
    Given an event without a venue address nor a summary
    When it is written as a calendar file
    Then its entry's location is the venue alone, and its description the link
    to its page alone
    """
    event = EventFactory(slug="loto-2026", venue_name="Salle des fêtes")

    (entry,) = entries(event_calendar(event, SITE))

    assert entry["LOCATION"] == "Salle des fêtes"
    assert entry["DESCRIPTION"] == "https://example.org/evenements/loto-2026"


def test_an_event_keeps_its_id_when_its_title_and_address_change():
    """
    Given an event already added to a calendar
    When its title and its address change
    Then its entry keeps its id: the calendar updates it rather than adding it
    again
    """
    event = EventFactory(title="Loto", slug="loto-2026")
    (before,) = entries(event_calendar(event, SITE))

    event.title, event.slug = "Super loto", "super-loto-2026"
    event.save()
    (after,) = entries(event_calendar(event, SITE))

    assert after["SUMMARY"] == "Super loto"
    assert after["UID"] == before["UID"]


def test_the_agenda_feed_is_named_and_refreshed_twice_a_day_unlike_an_event_file():
    """
    Given an event
    When the agenda and the event are written as calendars
    Then the agenda bears the committee's name and asks to be fetched every
    twelve hours at most
    And the event's file bears neither, since it is added to a calendar once
    """
    event = EventFactory()

    agenda = Calendar.from_ical(agenda_calendar([event], SITE))
    single = Calendar.from_ical(event_calendar(event, SITE))

    assert agenda.calendar_name == "Comité des fêtes d’Ons-en-Bray"
    assert agenda.refresh_interval == dt.timedelta(hours=12)
    assert single.calendar_name is None
    assert single.refresh_interval is None
    assert agenda.prodid == single.prodid == "-//Comité des fêtes d’Ons-en-Bray//Agenda//FR"


def test_an_empty_agenda_is_a_calendar_without_entries():
    """
    Given no event
    When the agenda is written as a calendar
    Then it is a valid calendar, without entries nor time zone
    """
    calendar = Calendar.from_ical(agenda_calendar([], SITE))

    assert calendar.events == []
    assert calendar.timezones == []
