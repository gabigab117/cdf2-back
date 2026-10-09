import datetime as dt
from io import StringIO
from zoneinfo import ZoneInfo

import pytest
from django.core.management import CommandError, call_command
from django.utils import timezone

from events.models import Event
from events.services.demo import DEMO_EVENTS, seed_demo_events
from events.services.events import event_slug
from events.services.periods import events_in_period

pytestmark = pytest.mark.django_db

PARIS = ZoneInfo("Europe/Paris")


def starts(title, slug_year=None):
    """When the demo event of that title starts, in Paris time."""
    events = Event.objects.filter(title=title)
    if slug_year is not None:
        events = events.filter(slug__endswith=str(slug_year))
    return timezone.localtime(events.get().starts_at)


# The command


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


# Their days


def test_the_events_to_come_take_their_next_day_and_the_past_ones_their_last():
    """
    Given today is Friday 9 October 2026
    When the demo events are written
    Then Halloween comes on 31 October 2026 and the meal of the elderly on
    17 January 2027, in winter time
    And the Fête du 14 juillet took place on 14 July 2026, in summer time
    """
    seed_demo_events(dt.date(2026, 10, 9))

    assert starts("Halloween des enfants") == dt.datetime(2026, 10, 31, 15, tzinfo=PARIS)
    assert starts("Halloween des enfants").utcoffset() == dt.timedelta(hours=1)
    assert starts("Repas des aînés") == dt.datetime(2027, 1, 17, 12, tzinfo=PARIS)
    assert starts("Fête du 14 juillet") == dt.datetime(2026, 7, 14, 19, tzinfo=PARIS)
    assert starts("Fête du 14 juillet").utcoffset() == dt.timedelta(hours=2)
    assert starts("Brocante", 2026) == dt.datetime(2026, 9, 13, 7, tzinfo=PARIS)


def test_an_event_of_today_is_to_come():
    """
    Given today is 31 October 2026, the day of Halloween
    When the demo events are written
    Then Halloween is today, with the events to come
    """
    seed_demo_events(dt.date(2026, 10, 31))

    assert starts("Halloween des enfants") == dt.datetime(2026, 10, 31, 15, tzinfo=PARIS)


def test_a_past_event_is_never_today():
    """
    Given today is 13 September 2026, the day of the Brocante
    When the demo events are written
    Then the Brocante took place on 13 September 2025
    """
    seed_demo_events(dt.date(2026, 9, 13))

    assert starts("Brocante") == dt.datetime(2025, 9, 13, 7, tzinfo=PARIS)


def test_the_egg_hunt_to_come_follows_the_last_one():
    """
    Given today is 9 October 2026
    When the demo events are written
    Then the egg hunt of 28 March 2027 has the egg hunt of 5 April 2026 as its
    previous edition
    """
    seed_demo_events(dt.date(2026, 10, 9))

    egg_hunt = Event.objects.get(slug="chasse-aux-oeufs-2027")
    assert egg_hunt.previous_edition.slug == "chasse-aux-oeufs-2026"
    assert timezone.localtime(egg_hunt.previous_edition.starts_at).date() == dt.date(2026, 4, 5)


# Running it again


def test_a_second_run_rewrites_the_events_without_adding_any():
    """
    Given the demo events, written on 9 October 2026, and Halloween's summary
    changed since
    When the demo events are written again the same day
    Then there are still nine events, and Halloween has its summary back
    """
    seed_demo_events(dt.date(2026, 10, 9))
    Event.objects.filter(title="Halloween des enfants").update(summary="Changé à la main.")

    seed_demo_events(dt.date(2026, 10, 9))

    assert Event.objects.count() == 9
    assert Event.objects.get(title="Halloween des enfants").summary.startswith("Défilé costumé")
    assert Event.objects.get(title="Halloween des enfants").programme.count() == 4


def test_a_run_after_a_day_has_gone_by_writes_the_next_edition():
    """
    Given the demo events, written on 9 October 2026
    When they are written again on 20 November 2026, after Halloween and the Loto
    Then Halloween and the Loto of 2027 are written, and those of 2026 stay past
    """
    seed_demo_events(dt.date(2026, 10, 9))

    seed_demo_events(dt.date(2026, 11, 20))

    assert Event.objects.count() == 11
    assert starts("Halloween des enfants", 2027).date() == dt.date(2027, 10, 31)
    assert starts("Loto d’automne", 2026).date() == dt.date(2026, 11, 15)


# Their address


def test_the_address_of_an_event_is_its_title_and_its_year_in_paris():
    """
    Given an event starting at 23:30 on 31 December 2026 in UTC, already 2027 in Paris
    When its address is derived
    Then it is made of its title, spelled out, and of the year 2027
    """
    new_year = dt.datetime(2026, 12, 31, 23, 30, tzinfo=dt.UTC)

    assert event_slug("Réveillon des œufs d’or", new_year) == "reveillon-des-oeufs-d-or-2027"
