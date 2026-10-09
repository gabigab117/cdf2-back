import datetime as dt

import pytest
from django.test import Client
from django.utils import timezone
from ninja_jwt.tokens import AccessToken

from events.models import Event, EventCategory
from tests.accounts.factories import BoardMemberFactory, UserFactory
from tests.events.factories import (
    EventFactory,
    PracticalInfoFactory,
    ProgrammeItemFactory,
    event_payload,
)

pytestmark = pytest.mark.django_db

EVENTS = "/api/board/events"

# Every operation on the events, the paths of a single event naming any id:
# a refusal comes before the event is looked up.
OPERATIONS = [
    ("get", EVENTS),
    ("post", EVENTS),
    ("get", f"{EVENTS}/1"),
    ("put", f"{EVENTS}/1"),
    ("delete", f"{EVENTS}/1"),
]


def event_url(event_id):
    return f"{EVENTS}/{event_id}"


def send(client, method, path, payload):
    return getattr(client, method)(path, payload, content_type="application/json")


def listed_titles(client, **params):
    return [item["title"] for item in client.get(EVENTS, params).json()["items"]]


# Access


@pytest.mark.parametrize(("method", "path"), OPERATIONS)
def test_events_are_reserved_to_signed_in_members(client, method, path):
    """
    Given a visitor without a session
    When they call any operation on the events
    Then they are refused with a 401
    """
    assert getattr(client, method)(path).status_code == 401


@pytest.mark.parametrize(("method", "path"), OPERATIONS)
def test_events_are_refused_to_accounts_outside_the_board(method, path):
    """
    Given an account outside the board, signed in
    When it calls any operation on the events
    Then it is refused with a 403
    """
    client = Client(headers={"Authorization": f"Bearer {AccessToken.for_user(UserFactory())}"})

    assert getattr(client, method)(path).status_code == 403


@pytest.mark.parametrize(
    ("method", "payload"), [("get", None), ("put", event_payload()), ("delete", None)]
)
def test_an_unknown_event_is_not_found(board_client, method, payload):
    """
    Given no event of id 987654
    When the board reads, rewrites or deletes it
    Then the answer is a 404, in French
    """
    response = send(board_client, method, event_url(987654), payload)

    assert response.status_code == 404
    assert response.json() == {"detail": "Introuvable."}


# List


def test_the_events_come_by_page(board_client):
    """
    Given three events
    When the board lists them by pages of two
    Then the first page holds two events, and the count tells there are three
    """
    EventFactory.create_batch(3)

    body = board_client.get(EVENTS, {"page_size": 2}).json()

    assert len(body["items"]) == 2
    assert body["count"] == 3


def test_a_listed_event_holds_what_the_lists_show(board_client):
    """
    Given a published event
    When the board lists the events
    Then the event comes with its title, address, category, dates, start label,
    venue and publication
    """
    starts_at = dt.datetime(2026, 11, 15, 12, tzinfo=dt.UTC)
    event = EventFactory(
        title="Loto d’automne",
        slug="loto-d-automne-2026",
        starts_at=starts_at,
        start_label="Ouverture",
        published=True,
    )

    assert board_client.get(EVENTS).json()["items"] == [
        {
            "id": event.pk,
            "title": "Loto d’automne",
            "slug": "loto-d-automne-2026",
            "category": "games",
            "starts_at": "2026-11-15T12:00:00Z",
            "ends_at": None,
            "start_label": "Ouverture",
            "venue_name": "Salle des fêtes",
            "published": True,
        }
    ]


def test_events_are_filtered_by_period_category_and_publication(board_client):
    """
    Given published games and markets to come, an unpublished game to come and
    a past game
    When the board filters the events
    Then each filter keeps its events, and the filters combine
    """
    soon = timezone.now() + dt.timedelta(days=7)
    EventFactory(title="Loto", published=True, starts_at=soon)
    EventFactory(title="Marché", category=EventCategory.MARKETS, published=True, starts_at=soon)
    EventFactory(title="Belote", starts_at=soon + dt.timedelta(days=1))
    EventFactory(title="Ancien loto", published=True, starts_at=soon - dt.timedelta(days=60))

    assert listed_titles(board_client, period="upcoming") == ["Loto", "Marché", "Belote"]
    assert listed_titles(board_client, period="past") == ["Ancien loto"]
    assert listed_titles(board_client, category="markets") == ["Marché"]
    assert listed_titles(board_client, published="false") == ["Belote"]
    assert listed_titles(board_client, period="upcoming", category="games", published="true") == [
        "Loto"
    ]


def test_an_unknown_filter_value_is_refused(board_client):
    """
    Given the board's events
    When they are filtered on a period that does not exist
    Then the request is refused with a 422, in French, under the period
    """
    response = board_client.get(EVENTS, {"period": "tomorrow"})

    assert response.status_code == 422
    assert response.json()["detail"] == [
        {
            "type": "literal_error",
            "loc": ["query", "period"],
            "msg": "Sélectionnez un choix valide. Ce choix ne fait pas partie de ceux disponibles.",
        }
    ]


# Detail


def test_an_event_comes_with_all_its_content(board_client):
    """
    Given an event led by a board member, following a previous edition, with
    programme lines and a practical info
    When the board reads it
    Then it comes with its lead, its previous edition and its lines in order
    """
    lead = BoardMemberFactory(first_name="Julie", last_name="Roux")
    previous = EventFactory(title="Halloween des enfants")
    event = EventFactory(lead=lead, previous_edition=previous, latitude=49.42, longitude=1.98)
    ProgrammeItemFactory(event=event, time=dt.time(17), title="Goûter", sort_order=1)
    ProgrammeItemFactory(event=event, time=dt.time(15), title="Accueil", sort_order=0)
    PracticalInfoFactory(event=event, title="Stationnement sur la place", text="Gratuit.")

    body = board_client.get(event_url(event.pk)).json()

    assert body["lead"] == {"id": lead.pk, "first_name": "Julie", "last_name": "Roux"}
    assert body["previous_edition"]["title"] == "Halloween des enfants"
    assert (body["latitude"], body["longitude"]) == (49.42, 1.98)
    assert body["programme"] == [
        {"time": "15:00:00", "title": "Accueil", "description": ""},
        {"time": "17:00:00", "title": "Goûter", "description": ""},
    ]
    assert body["practical_infos"] == [
        {"icon": "parking", "title": "Stationnement sur la place", "text": "Gratuit."}
    ]


def test_an_event_id_that_is_not_a_number_is_refused(board_client):
    """
    Given an address of an event whose id is not a number
    When the board reads it
    Then the request is refused with a 422, in French, under the id
    """
    response = board_client.get(event_url("abc"))

    assert response.status_code == 422
    assert response.json()["detail"] == [
        {"type": "int_parsing", "loc": ["path", "event_id"], "msg": "Saisissez un nombre entier."}
    ]


# Writing


def test_the_board_creates_an_event(board_client):
    """
    Given a board member to lead it
    When the board sends a new event, without an address
    Then the event is created, with an address derived from its title
    And the answer shows it whole, lead and programme included
    """
    lead = BoardMemberFactory()

    response = board_client.post(EVENTS, event_payload(lead=lead.pk), "application/json")

    assert response.status_code == 201
    body = response.json()
    assert body["slug"] == "halloween-des-enfants-2026"
    assert body["lead"]["id"] == lead.pk
    assert [line["title"] for line in body["programme"]] == ["Accueil et maquillage", "Goûter"]
    assert Event.objects.get(pk=body["id"]).title == "Halloween des enfants"


def test_an_address_already_used_is_refused_under_its_field(board_client):
    """
    Given an event at the address halloween-des-enfants-2026
    When the board creates another event that would take it
    Then the request is refused with a 422, located under the address
    """
    EventFactory(slug="halloween-des-enfants-2026")

    response = board_client.post(EVENTS, event_payload(), "application/json")

    assert response.status_code == 422
    assert response.json() == {
        "detail": [
            {
                "type": "validation_error",
                "loc": ["body", "slug"],
                "msg": "Un autre événement utilise déjà cette adresse.",
            }
        ]
    }


def test_a_faulty_line_is_refused_under_its_position(board_client):
    """
    Given an event whose second programme line has no title
    When the board sends it
    Then the request is refused with a 422, located under that line's title
    """
    payload = event_payload(
        programme=[
            {"time": "15:00", "title": "Accueil", "description": ""},
            {"time": "17:00", "title": "", "description": ""},
        ]
    )

    response = board_client.post(EVENTS, payload, "application/json")

    assert response.status_code == 422
    assert response.json()["detail"] == [
        {
            "type": "validation_error",
            "loc": ["body", "programme", 1, "title"],
            "msg": "Ce champ ne peut pas être vide.",
        }
    ]


def test_a_date_without_its_time_zone_is_refused(board_client):
    """
    Given an event whose start has no time zone
    When the board sends it
    Then the request is refused with a 422, in French, under the start
    """
    response = board_client.post(
        EVENTS, event_payload(starts_at="2026-10-31T15:00:00"), "application/json"
    )

    assert response.status_code == 422
    assert response.json()["detail"] == [
        {
            "type": "timezone_aware",
            "loc": ["body", "payload", "starts_at"],
            "msg": "Saisissez une date et une heure valides.",
        }
    ]


def test_the_errors_of_the_schema_are_reported_in_french_under_their_field(board_client):
    """
    Given an event without a title, of an unknown category, whose programme
    line has no time
    When the board sends it
    Then the request is refused with a 422 listing each error in French, under
    its field or its line
    """
    payload = event_payload(
        category="sport",
        programme=[{"time": "", "title": "Accueil", "description": ""}],
    )
    del payload["title"]

    response = board_client.post(EVENTS, payload, "application/json")

    assert response.status_code == 422
    assert response.json()["detail"] == [
        {
            "type": "missing",
            "loc": ["body", "payload", "title"],
            "msg": "Ce champ est obligatoire.",
        },
        {
            "type": "enum",
            "loc": ["body", "payload", "category"],
            "msg": "Sélectionnez un choix valide. Ce choix ne fait pas partie de ceux disponibles.",
        },
        {
            "type": "time_parsing",
            "loc": ["body", "payload", "programme", 0, "time"],
            "msg": "Saisissez une heure valide.",
        },
    ]


def test_the_board_rewrites_an_event_and_its_programme(board_client):
    """
    Given an event with a programme line
    When the board rewrites it with a new title and another programme
    Then the answer shows the new title and the new programme only
    """
    event = EventFactory()
    ProgrammeItemFactory(event=event, title="Ancienne animation")
    payload = event_payload(
        title="Loto de printemps",
        programme=[{"time": "14:00", "title": "Ouverture des portes", "description": ""}],
    )

    response = board_client.put(event_url(event.pk), payload, "application/json")

    assert response.status_code == 200
    assert response.json()["title"] == "Loto de printemps"
    assert [line["title"] for line in response.json()["programme"]] == ["Ouverture des portes"]


def test_the_board_deletes_an_event(board_client):
    """
    Given an event
    When the board deletes it
    Then the answer is empty, and the event is gone
    """
    event = EventFactory()

    response = board_client.delete(event_url(event.pk))

    assert response.status_code == 204
    assert not Event.objects.filter(pk=event.pk).exists()
