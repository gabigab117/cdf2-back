import pytest
from django.test import Client
from ninja_jwt.tokens import AccessToken

from stations.models import Assignment, Station
from tests.accounts.factories import UserFactory
from tests.events.factories import EventFactory
from tests.stations.factories import AssignmentFactory, StationFactory

pytestmark = pytest.mark.django_db

# Every operation on the stations, the paths naming any id: a refusal comes
# before anything is looked up.
OPERATIONS = [
    ("get", "/api/board/events/1/stations"),
    ("post", "/api/board/events/1/stations"),
    ("put", "/api/board/events/1/stations/order"),
    ("put", "/api/board/stations/1"),
    ("delete", "/api/board/stations/1"),
    ("post", "/api/board/stations/1/assignments"),
    ("delete", "/api/board/assignments/1"),
]


def stations_url(event_id):
    return f"/api/board/events/{event_id}/stations"


def station_url(station_id):
    return f"/api/board/stations/{station_id}"


def assignments_url(station_id):
    return f"{station_url(station_id)}/assignments"


def send(client, method, path, payload=None):
    return getattr(client, method)(path, payload, content_type="application/json")


def board(client, event):
    return client.get(stations_url(event.id)).json()


def staff(station, *names):
    for name in names:
        AssignmentFactory(station=station, name=name)


def station_payload(**changes):
    return {"name": "Buvette", "description": "Bière et soft.", "required_count": 3} | changes


# Access


@pytest.mark.parametrize(("method", "path"), OPERATIONS)
def test_stations_are_reserved_to_signed_in_members(client, method, path):
    """
    Given a visitor without a session
    When they call any operation on the stations
    Then they are refused with a 401
    """
    assert getattr(client, method)(path).status_code == 401


@pytest.mark.parametrize(("method", "path"), OPERATIONS)
def test_stations_are_refused_to_accounts_outside_the_board(method, path):
    """
    Given an account outside the board, signed in
    When it calls any operation on the stations
    Then it is refused with a 403
    """
    client = Client(headers={"Authorization": f"Bearer {AccessToken.for_user(UserFactory())}"})

    assert getattr(client, method)(path).status_code == 403


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("get", stations_url(987654), None),
        ("post", stations_url(987654), station_payload()),
        ("put", f"{stations_url(987654)}/order", {"stations": []}),
        ("put", station_url(987654), station_payload()),
        ("delete", station_url(987654), None),
        ("post", assignments_url(987654), {"name": "Alice", "role": ""}),
        ("delete", "/api/board/assignments/987654", None),
    ],
)
def test_an_unknown_event_station_or_volunteer_is_not_found(board_client, method, path, payload):
    """
    Given no event, station or volunteer of id 987654
    When the board acts on it
    Then the answer is a 404, in French
    """
    response = send(board_client, method, path, payload)

    assert response.status_code == 404
    assert response.json() == {"detail": "Introuvable."}


# The board of an event


def test_the_stations_of_an_event_come_with_their_people_and_totals(board_client):
    """
    Given an event whose « Caisse » requires 2 people and has Bob, and whose
    « Buvette » requires 3 and has Alice, as « bière uniquement »
    When the board opens the event's stations
    Then each station comes with its people, how many stand at it and whether
    it is complete
    And the event counts 2 people out of 5, with 3 places to fill
    """
    event = EventFactory()
    caisse = StationFactory(event=event, name="Caisse", required_count=2, sort_order=0)
    buvette = StationFactory(
        event=event, name="Buvette", description="Bière et soft.", required_count=3, sort_order=1
    )
    bob = AssignmentFactory(station=caisse, name="Bob")
    alice = AssignmentFactory(station=buvette, name="Alice", role="bière uniquement")

    assert board(board_client, event) == {
        "stations": [
            {
                "id": caisse.id,
                "name": "Caisse",
                "description": "",
                "required_count": 2,
                "assigned_count": 1,
                "complete": False,
                "assignments": [{"id": bob.id, "name": "Bob", "role": ""}],
            },
            {
                "id": buvette.id,
                "name": "Buvette",
                "description": "Bière et soft.",
                "required_count": 3,
                "assigned_count": 1,
                "complete": False,
                "assignments": [{"id": alice.id, "name": "Alice", "role": "bière uniquement"}],
            },
        ],
        "required_count": 5,
        "assigned_count": 2,
        "open_places": 3,
        "complete": False,
    }


def test_an_over_staffed_station_is_complete(board_client):
    """
    Given a station requiring one person, with two
    When the board opens the event's stations
    Then the station is complete, over-staffing being allowed, and so is the event
    """
    station = StationFactory(required_count=1)
    staff(station, "Alice", "Bob")

    body = board(board_client, station.event)

    assert (body["stations"][0]["complete"], body["complete"], body["open_places"]) == (
        True,
        True,
        0,
    )


def test_a_surplus_never_hides_a_shortfall(board_client):
    """
    Given an event whose « Caisse » requires 2 people and has 4, and whose
    « Frites » requires 2 and has none
    When the board opens the event's stations
    Then the event is not complete: 2 places are still to fill at the fries,
    though 4 people stand for 4 required
    """
    event = EventFactory()
    staff(StationFactory(event=event, name="Caisse", required_count=2), "A", "B", "C", "D")
    StationFactory(event=event, name="Frites", required_count=2)

    body = board(board_client, event)

    assert (body["assigned_count"], body["required_count"]) == (4, 4)
    assert (body["open_places"], body["complete"]) == (2, False)


def test_an_event_without_stations_is_not_complete(board_client):
    """
    Given an event without stations
    When the board opens its stations
    Then nothing is to fill, and the event is not complete either
    """
    assert board(board_client, EventFactory()) == {
        "stations": [],
        "required_count": 0,
        "assigned_count": 0,
        "open_places": 0,
        "complete": False,
    }


def test_reading_the_stations_takes_a_fixed_number_of_queries(
    board_client, django_assert_max_num_queries
):
    """
    Given an event with four stations of three people each
    When the board opens its stations
    Then the stations, their counts and their people take a fixed number of queries
    """
    event = EventFactory()
    for station in StationFactory.create_batch(4, event=event):
        staff(station, "A", "B", "C")

    # Authentication (2), the event, the stations with their counts, their people.
    with django_assert_max_num_queries(5):
        body = board(board_client, event)

    assert body["assigned_count"] == 12


# Writing a station


def test_a_station_is_added_after_the_others(board_client):
    """
    Given an event with two stations
    When the board adds the « Buvette », requiring 3 people
    Then the station is recorded after the others, and comes empty
    """
    event = EventFactory()
    StationFactory.create_batch(2, event=event)

    response = send(board_client, "post", stations_url(event.id), station_payload(name=" Buvette "))

    assert response.status_code == 201
    station = Station.objects.get(name="Buvette")
    assert station.sort_order == max(event.stations.values_list("sort_order", flat=True))
    assert response.json() == {
        "id": station.id,
        "name": "Buvette",
        "description": "Bière et soft.",
        "required_count": 3,
        "assigned_count": 0,
        "complete": False,
        "assignments": [],
    }


def test_the_first_station_of_an_event_comes_first(board_client):
    """
    Given an event without stations
    When the board adds one
    Then it is the first
    """
    event = EventFactory()

    send(board_client, "post", stations_url(event.id), station_payload())

    assert Station.objects.get().sort_order == 0


@pytest.mark.parametrize(
    ("change", "location", "message"),
    [
        ({"name": "   "}, ["body", "name"], "Ce champ ne peut pas être vide."),
        (
            {"required_count": 0},
            ["body", "required_count"],
            "Assurez-vous que cette valeur est supérieure ou égale à 1.",
        ),
        (
            {"required_count": -5},
            ["body", "required_count"],
            "Assurez-vous que cette valeur est supérieure ou égale à 1.",
        ),
        (
            {"required_count": "abc"},
            ["body", "payload", "required_count"],
            "Saisissez un nombre entier.",
        ),
    ],
    ids=["blank name", "nobody", "negative", "not a number"],
)
def test_a_faulty_station_is_refused_in_french_under_its_field(
    board_client, change, location, message
):
    """
    Given an event
    When the board adds a station named with spaces only, requiring nobody,
    fewer than nobody, or a number that is none
    Then the station is refused with a 422, in French, under the field at fault
    """
    response = send(
        board_client, "post", stations_url(EventFactory().id), station_payload() | change
    )

    assert response.status_code == 422
    assert [(error["loc"], error["msg"]) for error in response.json()["detail"]] == [
        (location, message)
    ]
    assert not Station.objects.exists()


def test_the_board_rewrites_a_station(board_client):
    """
    Given a station with one person
    When the board renames it and asks for one person only
    Then the station is saved, and is now complete
    """
    station = StationFactory(name="Buvette", required_count=2)
    staff(station, "Alice")

    response = send(
        board_client, "put", station_url(station.id), station_payload(name="Bar", required_count=1)
    )

    assert response.status_code == 200
    assert (response.json()["name"], response.json()["complete"]) == ("Bar", True)


def test_deleting_a_station_takes_its_volunteers_along(board_client):
    """
    Given a station with two people, and another station
    When the board deletes the first station
    Then the station and its people are gone, the other station stays
    """
    station = StationFactory()
    staff(station, "Alice", "Bob")
    other = StationFactory()

    response = board_client.delete(station_url(station.id))

    assert response.status_code == 204
    assert list(Station.objects.all()) == [other]
    assert not Assignment.objects.exists()


# Order


def test_the_board_reorders_the_stations_of_an_event(board_client):
    """
    Given an event with « Caisse », « Buvette » and « Frites », in that order
    When the board puts the fries first
    Then the stations come in the new order
    """
    event = EventFactory()
    caisse, buvette, frites = (
        StationFactory(event=event, name=name, sort_order=position)
        for position, name in enumerate(["Caisse", "Buvette", "Frites"])
    )

    response = send(
        board_client,
        "put",
        f"{stations_url(event.id)}/order",
        {"stations": [frites.id, caisse.id, buvette.id]},
    )

    assert response.status_code == 200
    assert [station["name"] for station in response.json()["stations"]] == [
        "Frites",
        "Caisse",
        "Buvette",
    ]


@pytest.mark.parametrize("order", ["missing", "twice", "foreign"])
def test_an_order_must_hold_each_station_of_the_event_once(board_client, order):
    """
    Given an event with two stations, and a station of another event
    When the board sends an order missing a station, naming one twice, or
    naming the other event's
    Then the order is refused with a 422, located under the stations, and
    nothing moves
    """
    event = EventFactory()
    first, second = StationFactory.create_batch(2, event=event)
    foreign = StationFactory()
    ids = {
        "missing": [second.id],
        "twice": [second.id, second.id],
        "foreign": [second.id, foreign.id],
    }[order]

    response = send(board_client, "put", f"{stations_url(event.id)}/order", {"stations": ids})

    assert response.status_code == 422
    assert response.json()["detail"] == [
        {
            "type": "validation_error",
            "loc": ["body", "stations"],
            "msg": "Donnez chaque poste de l’événement, une fois chacun.",
        }
    ]
    first.refresh_from_db()
    assert first.sort_order < Station.objects.get(pk=second.pk).sort_order


# Volunteers


def test_the_board_puts_a_volunteer_at_a_station(board_client):
    """
    Given a station
    When the board puts Alice at it, for the beer only
    Then Alice stands at the station with her role
    """
    station = StationFactory()

    response = send(
        board_client,
        "post",
        assignments_url(station.id),
        {"name": " Alice ", "role": "bière uniquement"},
    )

    assert response.status_code == 201
    assignment = station.assignments.get()
    assert (assignment.name, assignment.role) == ("Alice", "bière uniquement")
    assert response.json() == {"id": assignment.id, "name": "Alice", "role": "bière uniquement"}


def test_a_volunteer_without_a_role(board_client):
    """
    Given a station
    When the board puts Bob at it, without a role
    Then Bob stands at the station, his role empty
    """
    station = StationFactory()

    send(board_client, "post", assignments_url(station.id), {"name": "Bob", "role": ""})

    assert station.assignments.get().role == ""


@pytest.mark.parametrize("name", ["", "   "], ids=["empty", "spaces"])
def test_a_volunteer_needs_a_name(board_client, name):
    """
    Given a station
    When the board puts at it someone without a name, or a name of spaces only
    Then the volunteer is refused with a 422, under the name
    """
    station = StationFactory()

    response = send(board_client, "post", assignments_url(station.id), {"name": name, "role": ""})

    assert response.status_code == 422
    assert response.json()["detail"] == [
        {
            "type": "validation_error",
            "loc": ["body", "name"],
            "msg": "Ce champ ne peut pas être vide.",
        }
    ]
    assert not Assignment.objects.exists()


def test_the_board_takes_a_volunteer_off_a_station(board_client):
    """
    Given a station with Alice and Bob
    When the board takes Alice off it
    Then Bob alone stands at the station, and its count falls to one
    """
    station = StationFactory()
    staff(station, "Alice", "Bob")
    alice = station.assignments.get(name="Alice")

    response = board_client.delete(f"/api/board/assignments/{alice.id}")

    assert response.status_code == 204
    assert board(board_client, station.event)["stations"][0]["assigned_count"] == 1
