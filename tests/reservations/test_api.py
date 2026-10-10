import pytest
from django.core.serializers.json import DjangoJSONEncoder
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from ninja_jwt.tokens import AccessToken

from events.models import Event
from reservations.models import Reservation, ReservationLine, TicketType
from tests.accounts.factories import BoardMemberFactory, UserFactory
from tests.events.factories import EventFactory
from tests.reservations.factories import TicketTypeFactory, reserve

pytestmark = pytest.mark.django_db

# Every operation on the reservations, the paths naming any id: a refusal
# comes before anything is looked up.
OPERATIONS = [
    ("get", "/api/board/events/1/reservations"),
    ("post", "/api/board/events/1/reservations"),
    ("get", "/api/board/events/1/reservations/stats"),
    ("get", "/api/board/events/1/reservations.xlsx"),
    ("put", "/api/board/events/1/capacity"),
    ("post", "/api/board/events/1/ticket-types"),
    ("delete", "/api/board/ticket-types/1"),
    ("put", "/api/board/reservations/1"),
    ("delete", "/api/board/reservations/1"),
]


def reservations_url(event_id):
    return f"/api/board/events/{event_id}/reservations"


def reservation_url(reservation_id):
    return f"/api/board/reservations/{reservation_id}"


def send(client, method, path, payload=None):
    return getattr(client, method)(path, payload, content_type="application/json")


def iso(moment):
    """A time as the API writes it: to the millisecond, as Django's JSON does."""
    return DjangoJSONEncoder().default(moment)


@pytest.fixture
def menus():
    """A meal with two types of place, « Menu adulte » then « Menu enfant »,
    and a type of another event.
    """
    event = EventFactory(title="Repas des aînés")
    adult = TicketTypeFactory(event=event, name="Menu adulte", sort_order=0)
    child = TicketTypeFactory(event=event, name="Menu enfant", sort_order=1)
    TicketTypeFactory(name="Menu choucroute")
    return event, adult, child


def with_capacity(event, capacity):
    event.capacity = capacity
    event.save()
    return event


def lines(*pairs):
    return [
        {"ticket_type": ticket_type.id, "quantity": quantity} for ticket_type, quantity in pairs
    ]


def reservation_payload(*pairs, name="Famille Martin", note=""):
    return {"name": name, "note": note, "lines": lines(*pairs)}


def messages(response):
    return [(error["loc"], error["msg"]) for error in response.json()["detail"]]


# Access


@pytest.mark.parametrize(("method", "path"), OPERATIONS)
def test_reservations_are_reserved_to_signed_in_members(client, method, path):
    """
    Given a visitor without a session
    When they call any operation on the reservations
    Then they are refused with a 401
    """
    assert getattr(client, method)(path).status_code == 401


@pytest.mark.parametrize(("method", "path"), OPERATIONS)
def test_reservations_are_refused_to_accounts_outside_the_board(method, path):
    """
    Given an account outside the board, signed in
    When it calls any operation on the reservations
    Then it is refused with a 403
    """
    client = Client(headers={"Authorization": f"Bearer {AccessToken.for_user(UserFactory())}"})

    assert getattr(client, method)(path).status_code == 403


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("get", reservations_url(987654), None),
        ("post", reservations_url(987654), {"name": "Famille", "note": "", "lines": []}),
        ("get", f"{reservations_url(987654)}/stats", None),
        ("get", "/api/board/events/987654/reservations.xlsx", None),
        ("put", "/api/board/events/987654/capacity", {"capacity": 10}),
        ("post", "/api/board/events/987654/ticket-types", {"name": "Menu"}),
        ("delete", "/api/board/ticket-types/987654", None),
        ("put", reservation_url(987654), {"name": "Famille", "note": "", "lines": []}),
        ("delete", reservation_url(987654), None),
    ],
)
def test_an_unknown_event_type_or_reservation_is_not_found(board_client, method, path, payload):
    """
    Given no event, type of place or reservation of id 987654
    When the board acts on it
    Then the answer is a 404, in French
    """
    response = send(board_client, method, path, payload)

    assert response.status_code == 404
    assert response.json() == {"detail": "Introuvable."}


# Types of place


def test_the_board_adds_a_type_of_place_after_the_others(board_client, menus):
    """
    Given a meal with two types of place
    When the board adds « Assiette végétarienne »
    Then the type comes after the others
    """
    event, _adult, child = menus

    response = send(
        board_client, "post", f"/api/board/events/{event.id}/ticket-types", {"name": " Assiette "}
    )

    assert response.status_code == 201
    added = event.ticket_types.get(name="Assiette")
    assert response.json() == {"id": added.id, "name": "Assiette"}
    assert added.sort_order > child.sort_order


def test_the_first_type_of_an_event_comes_first(board_client):
    """
    Given an event without types of place
    When the board adds one
    Then it is the first
    """
    event = EventFactory()

    send(board_client, "post", f"/api/board/events/{event.id}/ticket-types", {"name": "Menu"})

    assert TicketType.objects.get().sort_order == 0


@pytest.mark.parametrize("name", ["Menu adulte", "MENU ADULTE"])
def test_a_type_of_place_is_unique_whatever_its_case(board_client, menus, name):
    """
    Given a meal with « Menu adulte »
    When the board adds « Menu adulte », or « MENU ADULTE »
    Then the type is refused with a 422, about the whole form
    """
    event, _adult, _child = menus

    response = send(
        board_client, "post", f"/api/board/events/{event.id}/ticket-types", {"name": name}
    )

    assert response.status_code == 422
    assert messages(response) == [(["body"], "Ce type de place existe déjà pour cet événement.")]


def test_another_event_may_have_a_type_of_the_same_name(board_client, menus):
    """
    Given a meal with « Menu adulte »
    When the board adds « Menu adulte » to another event
    Then the type is added
    """
    response = send(
        board_client,
        "post",
        f"/api/board/events/{EventFactory().id}/ticket-types",
        {"name": "Menu adulte"},
    )

    assert response.status_code == 201


def test_a_type_needs_a_name(board_client):
    """
    Given an event
    When the board adds a type named with spaces only
    Then the type is refused with a 422, under its name
    """
    response = send(
        board_client, "post", f"/api/board/events/{EventFactory().id}/ticket-types", {"name": "  "}
    )

    assert messages(response) == [(["body", "name"], "Ce champ ne peut pas être vide.")]


def test_an_unused_type_is_deleted(board_client, menus):
    """
    Given a meal whose « Menu enfant » no reservation uses
    When the board deletes it
    Then the type is gone
    """
    _event, _adult, child = menus

    response = board_client.delete(f"/api/board/ticket-types/{child.id}")

    assert response.status_code == 204
    assert not TicketType.objects.filter(pk=child.pk).exists()


def test_a_type_in_use_is_kept(board_client, menus):
    """
    Given a meal whose « Menu enfant » a reservation uses
    When the board deletes it
    Then the deletion is refused with a 422, which names the type, and it stays
    """
    event, _adult, child = menus
    reserve(event, enfant=(child, 1))

    response = board_client.delete(f"/api/board/ticket-types/{child.id}")

    assert response.status_code == 422
    assert messages(response) == [
        (["body"], "Impossible de supprimer « Menu enfant » : des réservations l’utilisent.")
    ]
    assert TicketType.objects.filter(pk=child.pk).exists()


# Recording a reservation


def test_the_board_records_a_reservation_by_type(board_client, menus):
    """
    Given a meal with two types of place
    When the board records 2 adults and 4 children for the Martin family, at
    table 4
    Then the reservation is recorded with its two lines, 6 places in all
    """
    event, adult, child = menus

    response = send(
        board_client,
        "post",
        reservations_url(event.id),
        reservation_payload((adult, 2), (child, 4), name=" Famille Martin ", note="Table 4"),
    )

    assert response.status_code == 201
    reservation = Reservation.objects.get()
    assert (reservation.event, reservation.name, reservation.note) == (
        event,
        "Famille Martin",
        "Table 4",
    )
    assert response.json() == {
        "id": reservation.id,
        "name": "Famille Martin",
        "note": "Table 4",
        "created_at": iso(reservation.created_at),
        "lines": [
            {"ticket_type": adult.id, "quantity": 2},
            {"ticket_type": child.id, "quantity": 4},
        ],
        "seats": 6,
    }


def test_a_reservation_takes_at_least_one_place(board_client, menus):
    """
    Given a meal
    When the board records a reservation without any place
    Then it is refused with a 422, about the whole form
    """
    event, _adult, _child = menus

    response = send(board_client, "post", reservations_url(event.id), reservation_payload())

    assert response.status_code == 422
    assert messages(response) == [(["body"], "Indiquez au moins une place.")]


@pytest.mark.parametrize(
    ("change", "location", "message"),
    [
        ({"name": "   "}, ["body", "name"], "Ce champ ne peut pas être vide."),
        ({"note": "x" * 256}, ["body", "note"], None),
    ],
    ids=["blank name", "long note"],
)
def test_a_reservation_is_refused_under_its_faulty_field(
    board_client, menus, change, location, message
):
    """
    Given a meal
    When the board records a reservation without a name, or with a remark too long
    Then it is refused with a 422, under the field at fault
    """
    event, adult, _child = menus

    response = send(
        board_client, "post", reservations_url(event.id), reservation_payload((adult, 1)) | change
    )

    assert response.status_code == 422
    [(found, text)] = messages(response)
    assert found == location
    assert message is None or text == message


@pytest.mark.parametrize("quantity", [0, -2])
def test_a_line_takes_at_least_one_place(board_client, menus, quantity):
    """
    Given a meal
    When the board records a line of no place, or fewer
    Then it is refused with a 422, under the quantity of that line
    """
    event, adult, child = menus

    response = send(
        board_client,
        "post",
        reservations_url(event.id),
        reservation_payload((adult, 1), (child, quantity)),
    )

    assert messages(response) == [
        (
            ["body", "lines", 1, "quantity"],
            "Assurez-vous que cette valeur est supérieure ou égale à 1.",
        )
    ]


def test_a_type_of_another_event_is_refused_under_its_line(board_client, menus):
    """
    Given a meal, and a type of place of another event
    When the board records places of that other type
    Then the reservation is refused with a 422, under the type of that line
    And nothing is recorded
    """
    event, adult, _child = menus
    foreign = TicketType.objects.get(name="Menu choucroute")

    response = send(
        board_client,
        "post",
        reservations_url(event.id),
        reservation_payload((adult, 1), (foreign, 2)),
    )

    assert response.status_code == 422
    assert messages(response) == [
        (
            ["body", "lines", 1, "ticket_type"],
            "Le type de place n’appartient pas à l’événement de la réservation.",
        )
    ]
    assert not Reservation.objects.exists()


def test_an_unknown_type_is_refused_under_its_line(board_client, menus):
    """
    Given a meal
    When the board records places of a type that does not exist
    Then the reservation is refused with a 422, under the type of that line
    """
    event, _adult, _child = menus

    response = send(
        board_client,
        "post",
        reservations_url(event.id),
        {"name": "Famille", "note": "", "lines": [{"ticket_type": 987654, "quantity": 1}]},
    )

    assert messages(response) == [
        (["body", "lines", 0, "ticket_type"], "Choisissez un type de place existant.")
    ]


def test_a_type_given_twice_is_refused_under_its_second_line(board_client, menus):
    """
    Given a meal
    When the board sends two lines of « Menu adulte »
    Then the reservation is refused with a 422, under the type of the second line
    """
    event, adult, _child = menus

    response = send(
        board_client,
        "post",
        reservations_url(event.id),
        reservation_payload((adult, 1), (adult, 2)),
    )

    assert messages(response) == [
        (["body", "lines", 1, "ticket_type"], "Ce type de place figure déjà dans la réservation.")
    ]


# Capacity


@pytest.mark.parametrize(
    ("requested", "outcome"),
    [
        (6, None),
        (7, "Capacité dépassée : il ne reste que 6 places sur 10."),
    ],
    ids=["exact fit", "over"],
)
def test_the_capacity_takes_the_last_places_only(board_client, menus, requested, outcome):
    """
    Given a meal of 10 places, 4 of them reserved
    When the board records 6 places, then 7
    Then the 6 fit exactly, the 7 are refused, saying how many remain
    """
    event, adult, child = menus
    with_capacity(event, 10)
    reserve(event, adulte=(adult, 4))

    response = send(
        board_client, "post", reservations_url(event.id), reservation_payload((child, requested))
    )

    if outcome is None:
        assert response.status_code == 201
    else:
        assert messages(response) == [(["body"], outcome)]


def test_a_single_remaining_place_is_said_in_the_singular(board_client, menus):
    """
    Given a meal of 6 places, 5 of them reserved
    When the board records 2 places
    Then they are refused, the place left said in the singular
    """
    event, adult, _child = menus
    with_capacity(event, 6)
    reserve(event, adulte=(adult, 5))

    response = send(
        board_client, "post", reservations_url(event.id), reservation_payload((adult, 2))
    )

    assert messages(response) == [(["body"], "Capacité dépassée : il ne reste que 1 place sur 6.")]


def test_a_full_event_takes_no_more_places(board_client, menus):
    """
    Given a meal of 6 places, all reserved
    When the board records one more
    Then it is refused: the event is full
    """
    event, adult, _child = menus
    with_capacity(event, 6)
    reserve(event, adulte=(adult, 6))

    response = send(
        board_client, "post", reservations_url(event.id), reservation_payload((adult, 1))
    )

    assert messages(response) == [(["body"], "Complet : les 6 places sont déjà réservées.")]


def test_an_event_without_capacity_takes_any_number_of_places(board_client, menus):
    """
    Given a meal without capacity
    When the board records 500 places
    Then they are recorded
    """
    event, adult, _child = menus

    response = send(
        board_client, "post", reservations_url(event.id), reservation_payload((adult, 500))
    )

    assert response.status_code == 201


def test_recording_a_reservation_locks_its_event(board_client, menus):
    """
    Given a meal
    When the board records a reservation
    Then the event is locked first: two reservations at once cannot both take
    the last places
    """
    event, adult, _child = menus

    with CaptureQueriesContext(connection) as queries:
        send(board_client, "post", reservations_url(event.id), reservation_payload((adult, 1)))

    locks = [query["sql"] for query in queries.captured_queries if "FOR UPDATE" in query["sql"]]
    assert len(locks) == 1
    assert Event._meta.db_table in locks[0]


def test_a_reservation_is_written_whole_or_not_at_all(board_client, menus, monkeypatch):
    """
    Given a meal
    When recording the lines of a reservation fails
    Then the reservation itself is not recorded either
    """
    event, adult, _child = menus

    def fail(*args, **kwargs):
        raise RuntimeError

    monkeypatch.setattr(ReservationLine.objects, "bulk_create", fail)
    with pytest.raises(RuntimeError):
        send(board_client, "post", reservations_url(event.id), reservation_payload((adult, 1)))

    assert not Reservation.objects.exists()


# Rewriting a reservation


def test_rewriting_a_reservation_replaces_its_lines(board_client, menus):
    """
    Given a reservation of 2 adults and 4 children
    When the board rewrites it as 3 children and a remark
    Then the reservation holds 3 children only, with its remark
    """
    event, adult, child = menus
    reservation = reserve(event, adulte=(adult, 2), enfant=(child, 4))

    response = send(
        board_client,
        "put",
        reservation_url(reservation.id),
        reservation_payload((child, 3), name="Famille Martin", note="Près de la scène"),
    )

    assert response.status_code == 200
    assert response.json()["lines"] == [{"ticket_type": child.id, "quantity": 3}]
    assert (response.json()["note"], response.json()["seats"]) == ("Près de la scène", 3)
    assert ReservationLine.objects.count() == 1


def test_an_increase_counts_the_reservations_own_places_once(board_client, menus):
    """
    Given a meal of 20 places, 15 of them in a single reservation
    When the board raises that reservation to 16
    Then it is saved: its own 15 places are not counted twice
    """
    event, adult, _child = menus
    with_capacity(event, 20)
    reservation = reserve(event, adulte=(adult, 15))

    response = send(
        board_client, "put", reservation_url(reservation.id), reservation_payload((adult, 16))
    )

    assert response.status_code == 200


def test_an_increase_beyond_the_places_left_is_refused(board_client, menus):
    """
    Given a meal of 20 places, 15 in one reservation and 3 in another
    When the board raises the first to 18
    Then it is refused: 2 places only remain
    """
    event, adult, _child = menus
    with_capacity(event, 20)
    reservation = reserve(event, adulte=(adult, 15))
    reserve(event, name="Famille Petit", adulte=(adult, 3))

    response = send(
        board_client, "put", reservation_url(reservation.id), reservation_payload((adult, 18))
    )

    assert messages(response) == [
        (["body"], "Capacité dépassée : il ne reste que 2 places sur 20.")
    ]


def test_a_reduction_or_a_new_name_passes_on_an_event_over_its_capacity(board_client, menus):
    """
    Given a meal whose capacity was lowered to 10 under its 16 places reserved
    When the board lowers a reservation, then renames another, its places kept
    Then both are saved: only an increase meets the capacity
    """
    event, adult, _child = menus
    first = reserve(event, adulte=(adult, 8))
    second = reserve(event, name="Famille Petit", adulte=(adult, 8))
    with_capacity(event, 10)

    lowered = send(board_client, "put", reservation_url(first.id), reservation_payload((adult, 7)))
    renamed = send(
        board_client,
        "put",
        reservation_url(second.id),
        reservation_payload((adult, 8), name="Petit"),
    )

    assert (lowered.status_code, renamed.status_code) == (200, 200)


def test_an_increase_on_a_full_event_is_refused(board_client, menus):
    """
    Given a meal of 16 places, all reserved by one reservation
    When the board raises it to 17
    Then it is refused: the event is full
    """
    event, adult, _child = menus
    with_capacity(event, 16)
    reservation = reserve(event, adulte=(adult, 16))

    response = send(
        board_client, "put", reservation_url(reservation.id), reservation_payload((adult, 17))
    )

    assert messages(response) == [(["body"], "Complet : les 16 places sont déjà réservées.")]


def test_a_reservation_is_deleted_with_its_lines(board_client, menus):
    """
    Given a reservation of a menu
    When the board deletes it
    Then the reservation and its line are gone, and the menu may be deleted
    """
    event, adult, _child = menus
    reservation = reserve(event, adulte=(adult, 2))

    response = board_client.delete(reservation_url(reservation.id))

    assert response.status_code == 204
    assert not ReservationLine.objects.exists()
    assert board_client.delete(f"/api/board/ticket-types/{adult.id}").status_code == 204


# Reading the reservations


def test_the_reservations_come_the_latest_first_with_their_places(board_client, menus):
    """
    Given a meal with two reservations, and a reservation of another event
    When the board lists the meal's reservations
    Then they come the latest first, each with its lines and places
    """
    event, adult, child = menus
    first = reserve(event, name="Famille Martin", adulte=(adult, 2), enfant=(child, 4))
    second = reserve(event, name="Famille Petit", enfant=(child, 1))
    reserve(EventFactory(), name="Ailleurs")

    body = board_client.get(reservations_url(event.id)).json()

    assert body["count"] == 2
    assert [(item["id"], item["seats"]) for item in body["items"]] == [
        (second.id, 1),
        (first.id, 6),
    ]


def test_listing_the_reservations_reads_their_places_at_once(
    board_client, menus, django_assert_max_num_queries
):
    """
    Given a meal with five reservations of two lines each
    When the board lists them
    Then the reservations and their lines take a fixed number of queries
    """
    event, adult, child = menus
    for index in range(5):
        reserve(event, name=f"Famille {index}", adulte=(adult, 1), enfant=(child, 2))

    # Authentication (2), the event, count and page of reservations, their lines.
    with django_assert_max_num_queries(6):
        response = board_client.get(reservations_url(event.id))

    assert len(response.json()["items"]) == 5


def test_the_figures_of_the_reservations(board_client, menus):
    """
    Given a meal of 10 places, with two reservations of 6 and 1 places
    When the board opens its reservations
    Then it reads 2 reservations, 7 places, 3 remaining, and the places by type
    """
    event, adult, child = menus
    with_capacity(event, 10)
    reserve(event, adulte=(adult, 2), enfant=(child, 4))
    reserve(event, name="Famille Petit", enfant=(child, 1))

    assert board_client.get(f"{reservations_url(event.id)}/stats").json() == {
        "capacity": 10,
        "reservations": 2,
        "seats": 7,
        "remaining": 3,
        "ticket_types": [
            {"id": adult.id, "name": "Menu adulte", "seats": 2, "reservations": 1},
            {"id": child.id, "name": "Menu enfant", "seats": 5, "reservations": 2},
        ],
    }


def test_without_capacity_nothing_remains_to_count_and_never_below_zero(board_client, menus):
    """
    Given a meal without capacity, then with a capacity below its places
    When the board opens its reservations
    Then nothing remains to count without capacity, and none remain once over it
    """
    event, adult, _child = menus
    reserve(event, adulte=(adult, 8))
    url = f"{reservations_url(event.id)}/stats"

    unlimited = board_client.get(url).json()
    with_capacity(event, 6)
    over = board_client.get(url).json()

    assert (unlimited["capacity"], unlimited["remaining"]) == (None, None)
    assert (over["capacity"], over["remaining"]) == (6, 0)


# Capacity


def test_the_board_sets_and_lifts_the_capacity(board_client, menus):
    """
    Given a meal without capacity, whose last change was a month ago
    When the board sets 80 places, then lifts the limit
    Then the figures follow each time, and the date of the event's last change stays
    """
    event, _adult, _child = menus
    Event.objects.filter(pk=event.pk).update(updated_at=event.updated_at.replace(year=2025))
    url = f"/api/board/events/{event.id}/capacity"

    limited = send(board_client, "put", url, {"capacity": 80})
    unlimited = send(board_client, "put", url, {"capacity": None})

    assert (limited.json()["capacity"], limited.json()["remaining"]) == (80, 80)
    assert unlimited.json()["capacity"] is None
    event.refresh_from_db()
    assert (event.capacity, event.updated_at.year) == (None, 2025)


def test_a_capacity_takes_at_least_one_place(board_client, menus):
    """
    Given a meal
    When the board sets a capacity of no place
    Then it is refused with a 422, under the capacity
    """
    event, _adult, _child = menus

    response = send(board_client, "put", f"/api/board/events/{event.id}/capacity", {"capacity": 0})

    assert messages(response) == [
        (["body", "capacity"], "Assurez-vous que cette valeur est supérieure ou égale à 1.")
    ]


def test_the_capacity_ignores_the_rest_of_the_event(board_client, menus):
    """
    Given a meal led by a member who has left the board since
    When the board sets its capacity
    Then the capacity is saved: the lead is not the reservations' to judge
    """
    event, _adult, _child = menus
    former = BoardMemberFactory()
    event.lead = former
    event.save()
    former.groups.clear()

    response = send(board_client, "put", f"/api/board/events/{event.id}/capacity", {"capacity": 50})

    assert response.status_code == 200
