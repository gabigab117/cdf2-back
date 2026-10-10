import datetime as dt

import pytest
from django.core.serializers.json import DjangoJSONEncoder
from django.test import Client
from django.utils import timezone
from ninja_jwt.tokens import AccessToken

from tests.accounts.factories import UserFactory
from tests.events.factories import EventFactory

pytestmark = pytest.mark.django_db

OVERVIEW = "/api/board/overview"


def in_days(days):
    return timezone.now() + dt.timedelta(days=days)


def iso(moment):
    """A time as the API writes it: to the millisecond, as Django's JSON does."""
    return DjangoJSONEncoder().default(moment)


def listed_titles(client):
    return [item["title"] for item in client.get(OVERVIEW).json()["upcoming_events"]]


# Access


def test_the_overview_is_reserved_to_signed_in_members(client):
    """
    Given a visitor without a session
    When they ask for the board's overview
    Then they are refused with a 401
    """
    assert client.get(OVERVIEW).status_code == 401


def test_the_overview_is_refused_to_accounts_outside_the_board():
    """
    Given an account outside the board, signed in
    When it asks for the board's overview
    Then it is refused with a 403
    """
    client = Client(headers={"Authorization": f"Bearer {AccessToken.for_user(UserFactory())}"})

    assert client.get(OVERVIEW).status_code == 403


# Upcoming events


def test_the_overview_gives_the_next_five_events_and_how_many_are_to_come(board_client):
    """
    Given six events to come, one running since yesterday and one still a
    draft, and a past event
    When a member opens the dashboard
    Then it gets the first five, the running one first and the draft among them
    And it is told that six events are to come
    """
    EventFactory(title="Brocante", starts_at=in_days(-1), ends_at=in_days(1), published=True)
    EventFactory(title="Loto", starts_at=in_days(5), published=True)
    EventFactory(title="Halloween", starts_at=in_days(2), published=True)
    EventFactory(title="Repas", starts_at=in_days(3))
    EventFactory(title="Marché", starts_at=in_days(60), published=True)
    EventFactory(title="Saint-Jean", starts_at=in_days(90), published=True)
    EventFactory(title="Fête passée", starts_at=in_days(-30), published=True)

    response = board_client.get(OVERVIEW)

    assert response.status_code == 200
    body = response.json()
    assert [item["title"] for item in body["upcoming_events"]] == [
        "Brocante",
        "Halloween",
        "Repas",
        "Loto",
        "Marché",
    ]
    assert body["upcoming_events_count"] == 6


def test_an_event_of_the_overview_is_a_row_of_the_list(board_client):
    """
    Given a published event to come
    When a member opens the dashboard
    Then the event is written as a row of the board's list
    """
    halloween = EventFactory(
        title="Halloween",
        slug="halloween-2026",
        category="children",
        starts_at=in_days(2),
        start_label="Ouverture",
        published=True,
    )

    assert board_client.get(OVERVIEW).json()["upcoming_events"] == [
        {
            "id": halloween.id,
            "title": "Halloween",
            "slug": "halloween-2026",
            "category": "children",
            "starts_at": iso(halloween.starts_at),
            "ends_at": None,
            "start_label": "Ouverture",
            "venue_name": "Salle des fêtes",
            "published": True,
        }
    ]


def test_events_starting_together_come_the_first_recorded_first(board_client):
    """
    Given two events starting at the same time
    When a member opens the dashboard
    Then the one recorded first comes first
    """
    moment = in_days(4)
    EventFactory(title="Premier", starts_at=moment)
    EventFactory(title="Second", starts_at=moment)

    assert listed_titles(board_client) == ["Premier", "Second"]


def test_an_empty_board_has_no_event_to_come(board_client):
    """
    Given no event at all
    When a member opens the dashboard
    Then it gets no event, and none is counted to come
    """
    assert board_client.get(OVERVIEW).json() == {
        "upcoming_events": [],
        "upcoming_events_count": 0,
    }
