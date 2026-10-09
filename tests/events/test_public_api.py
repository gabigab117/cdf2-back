import datetime as dt

import pytest
from django.core.serializers.json import DjangoJSONEncoder
from django.test import Client
from django.utils import timezone
from icalendar import Calendar

from events.models import EventCategory
from tests.accounts.factories import BoardMemberFactory
from tests.events.factories import EventFactory, PracticalInfoFactory, ProgrammeItemFactory

pytestmark = pytest.mark.django_db

EVENTS = "/api/public/events"
AGENDA = "/api/public/agenda"
AGENDA_FEED = "/api/public/agenda.ics"


def in_days(days):
    return timezone.now() + dt.timedelta(days=days)


def iso(moment):
    """A time as the API writes it: to the millisecond, as Django's JSON does."""
    return DjangoJSONEncoder().default(moment)


def published(title, days, **fields):
    return EventFactory(title=title, starts_at=in_days(days), published=True, **fields)


def listed_titles(client, **params):
    return [item["title"] for item in client.get(EVENTS, params).json()["items"]]


# Agenda


def test_the_agenda_lists_the_published_events_to_come_the_next_first(client):
    """
    Given published events in five and two days, a draft in three days and a
    past published event
    When a visitor reads the agenda
    Then the published events to come are listed, the next first
    """
    published("Loto", 5)
    published("Halloween", 2)
    EventFactory(title="Repas", starts_at=in_days(3))
    published("Marché", -30)

    assert listed_titles(client) == ["Halloween", "Loto"]


def test_the_agenda_comes_by_page(client):
    """
    Given three published events to come
    When a visitor reads the agenda by pages of two
    Then the first page holds two events, and the count tells there are three
    """
    for days in (1, 2, 3):
        published(f"Event {days}", days)

    body = client.get(EVENTS, {"page_size": 2}).json()

    assert len(body["items"]) == 2
    assert body["count"] == 3


def test_an_agenda_event_holds_what_the_site_shows_and_no_one_s_name(client):
    """
    Given a published event led by a board member
    When a visitor reads the agenda
    Then the event comes with its address, title, category, dates, start
    label, venue and prices
    And neither its lead, its id nor its publication
    """
    starts_at = in_days(30)
    EventFactory(
        title="Loto d’automne",
        slug="loto-d-automne-2026",
        starts_at=starts_at,
        start_label="Ouverture",
        price_label="3 € le carton",
        price_detail="Buvette sur place",
        published=True,
        lead=BoardMemberFactory(),
    )

    assert client.get(EVENTS).json()["items"] == [
        {
            "slug": "loto-d-automne-2026",
            "title": "Loto d’automne",
            "category": "games",
            "starts_at": iso(starts_at),
            "ends_at": None,
            "start_label": "Ouverture",
            "venue_name": "Salle des fêtes",
            "price_label": "3 € le carton",
            "price_detail": "Buvette sur place",
        }
    ]


def test_the_agenda_is_filtered_by_category(client):
    """
    Given a published game and a published market to come
    When a visitor filters the agenda on the markets
    Then only the market is listed
    """
    published("Loto", 2)
    published("Marché de Noël", 3, category=EventCategory.MARKETS)

    assert listed_titles(client, category="markets") == ["Marché de Noël"]


def test_no_query_brings_a_draft_into_the_agenda(client):
    """
    Given a published event and a draft, both to come
    When a visitor asks the agenda for unpublished events, as the board's
    list allows
    Then the published event alone is listed: the agenda has no such filter
    """
    published("Loto", 2)
    EventFactory(title="Repas", starts_at=in_days(3))

    assert listed_titles(client, published="false") == ["Loto"]


def test_an_unknown_category_is_refused(client):
    """
    Given the agenda
    When a visitor filters it on a category that does not exist
    Then the request is refused with a 422, in French, under the category
    """
    response = client.get(EVENTS, {"category": "sport"})

    assert response.status_code == 422
    assert response.json()["detail"] == [
        {
            "type": "enum",
            "loc": ["query", "category"],
            "msg": "Sélectionnez un choix valide. Ce choix ne fait pas partie de ceux disponibles.",
        }
    ]


def test_a_token_that_is_no_longer_valid_does_not_keep_anyone_from_the_site():
    """
    Given a board member's browser still sending an access token that has
    expired
    When it reads the agenda
    Then the agenda answers: the site never checks who is reading
    """
    published("Loto", 2)
    client = Client(headers={"Authorization": "Bearer expired-token"})

    response = client.get(EVENTS)

    assert response.status_code == 200
    assert response.json()["count"] == 1


# Overview of the agenda


def test_the_agenda_tells_its_categories_and_its_last_change(client):
    """
    Given a published game and a published children's event to come
    When a visitor's page asks what surrounds the agenda
    Then it gets the two categories in their usual order, and the time the
    board last changed one of the events
    """
    published("Loto", 5)
    halloween = published("Halloween", 2, category=EventCategory.CHILDREN)

    assert client.get(AGENDA).json() == {
        "categories": ["children", "games"],
        "updated_at": iso(halloween.updated_at),
    }


def test_an_empty_agenda_has_no_category_and_no_last_change(client):
    """
    Given no published event to come
    When a visitor's page asks what surrounds the agenda
    Then it gets no category and no date
    """
    assert client.get(AGENDA).json() == {"categories": [], "updated_at": None}


# Event page


def test_an_event_page_holds_its_public_content_and_the_next_events(client):
    """
    Given a published event led by a board member, with programme lines, a
    practical info and coordinates, followed by two published events and a
    third
    When a visitor reads its page
    Then it comes with its content, its lines in order, and the next two events
    And with no one's name
    """
    event = published(
        "Halloween des enfants",
        2,
        slug="halloween-des-enfants-2026",
        category=EventCategory.CHILDREN,
        venue_address="1 place de la Mairie",
        latitude=49.42,
        longitude=1.98,
        price_label="Gratuit",
        price_detail="Goûter offert par le comité",
        summary="Défilé costumé, puis goûter.",
        lead=BoardMemberFactory(first_name="Julie", last_name="Roux"),
    )
    ProgrammeItemFactory(event=event, time=dt.time(17), title="Goûter", sort_order=1)
    ProgrammeItemFactory(event=event, time=dt.time(15), title="Accueil", sort_order=0)
    PracticalInfoFactory(event=event, title="Enfants accompagnés", text="Un adulte par groupe.")
    loto = published("Loto", 5, slug="loto-2026")
    published("Marché", 9)
    published("Repas", 12)

    response = client.get(f"{EVENTS}/halloween-des-enfants-2026")

    assert response.status_code == 200
    body = response.json()
    next_events = body.pop("next_events")
    assert body == {
        "slug": "halloween-des-enfants-2026",
        "title": "Halloween des enfants",
        "category": "children",
        "starts_at": iso(event.starts_at),
        "ends_at": None,
        "start_label": "",
        "venue_name": "Salle des fêtes",
        "venue_address": "1 place de la Mairie",
        "latitude": 49.42,
        "longitude": 1.98,
        "price_label": "Gratuit",
        "price_detail": "Goûter offert par le comité",
        "summary": "Défilé costumé, puis goûter.",
        "programme": [
            {"time": "15:00:00", "title": "Accueil", "description": ""},
            {"time": "17:00:00", "title": "Goûter", "description": ""},
        ],
        "practical_infos": [
            {"icon": "parking", "title": "Enfants accompagnés", "text": "Un adulte par groupe."}
        ],
    }
    assert [item["title"] for item in next_events] == ["Loto", "Marché"]
    assert next_events[0]["slug"] == loto.slug


def test_a_past_published_event_keeps_its_page(client):
    """
    Given a published event of last year
    When a visitor follows a link to its page
    Then the page answers, as it will for the previous edition of an event
    """
    published("Halloween des enfants", -365, slug="halloween-des-enfants-2025")

    response = client.get(f"{EVENTS}/halloween-des-enfants-2025")

    assert response.status_code == 200
    assert response.json()["title"] == "Halloween des enfants"


@pytest.mark.parametrize("suffix", ["", ".ics"], ids=["page", "calendar file"])
@pytest.mark.parametrize("slug", ["repas-des-aines-2027", "inconnu"], ids=["draft", "unknown"])
def test_a_draft_or_an_unknown_address_is_not_found(client, slug, suffix):
    """
    Given a draft at the address repas-des-aines-2027, and nothing elsewhere
    When a visitor asks for the page or the calendar file at either address
    Then the answer is a 404, in French
    """
    EventFactory(slug="repas-des-aines-2027")

    response = client.get(f"{EVENTS}/{slug}{suffix}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Introuvable."}


# Calendar files


def test_the_agenda_feed_holds_every_published_event_past_ones_included(client):
    """
    Given a published event to come, a past published event and a draft
    When a visitor's calendar fetches the agenda's feed
    Then it gets a calendar file holding both published events, the oldest
    first, without the draft
    """
    published("Loto", 5)
    published("Marché", -30)
    EventFactory(title="Repas", starts_at=in_days(3))

    response = client.get(AGENDA_FEED)

    assert response.status_code == 200
    assert response["Content-Type"] == "text/calendar; charset=utf-8"
    assert response["Content-Disposition"] == 'attachment; filename="agenda.ics"'
    calendar = Calendar.from_ical(response.content)
    assert [entry["SUMMARY"] for entry in calendar.events] == ["Marché", "Loto"]


def test_an_event_s_calendar_file_holds_that_event_with_links_to_the_site(client):
    """
    Given a published event at the address loto-2026
    When a visitor asks for its calendar file, which no event page answers
    Then they get a file named after the event, holding its entry alone
    And the entry links to the event's page on the site it was asked from
    """
    event = published("Loto", 5, slug="loto-2026")
    published("Marché", 9)

    response = client.get(f"{EVENTS}/loto-2026.ics")

    assert response.status_code == 200
    assert response["Content-Type"] == "text/calendar; charset=utf-8"
    assert response["Content-Disposition"] == 'attachment; filename="loto-2026.ics"'
    (entry,) = Calendar.from_ical(response.content).events
    assert entry["SUMMARY"] == "Loto"
    assert entry["URL"] == "http://testserver/evenements/loto-2026"
    assert entry["UID"] == f"event-{event.pk}@testserver"
