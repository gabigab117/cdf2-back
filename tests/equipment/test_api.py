import datetime as dt

import pytest
from django.test import Client
from django.utils import timezone
from ninja_jwt.tokens import AccessToken

from equipment.models import EquipmentCategory
from tests.accounts.factories import UserFactory
from tests.equipment.factories import EquipmentFactory, lend
from tests.events.factories import EventFactory

pytestmark = pytest.mark.django_db

EQUIPMENT = "/api/board/equipment"
AVAILABILITY = f"{EQUIPMENT}/availability"

# Every operation on the equipment and the loans, the paths of a single one
# naming any id: a refusal comes before any lookup.
OPERATIONS = [
    ("get", EQUIPMENT),
    ("post", EQUIPMENT),
    ("get", AVAILABILITY),
    ("put", f"{EQUIPMENT}/1"),
    ("delete", f"{EQUIPMENT}/1"),
    ("get", f"{EQUIPMENT}/1/occupancy"),
    ("get", "/api/board/loans"),
    ("post", "/api/board/loans"),
    ("get", "/api/board/loans/counts"),
    ("get", "/api/board/loans/deposits"),
    ("get", "/api/board/loans/1"),
    ("put", "/api/board/loans/1"),
    ("post", "/api/board/loans/1/checkout"),
    ("post", "/api/board/loans/1/return"),
    ("post", "/api/board/loans/1/reopen"),
    ("post", "/api/board/loans/1/cancel"),
]


def client_of(member):
    return Client(headers={"Authorization": f"Bearer {AccessToken.for_user(member)}"})


def ahead(days):
    return timezone.localdate() + dt.timedelta(days=days)


def period(start, end):
    return {"start": start.isoformat(), "end": end.isoformat()}


# Access


@pytest.mark.parametrize(("method", "path"), OPERATIONS)
def test_an_anonymous_visitor_gets_a_401(client, method, path):
    """
    Given a visitor without an access token
    When they read, add, change or delete equipment or loans, or what is free
    Then the API refuses with a 401
    """
    response = getattr(client, method)(path)

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentification requise."}


@pytest.mark.parametrize(("method", "path"), OPERATIONS)
def test_an_account_outside_the_board_gets_a_403(method, path):
    """
    Given an active account outside the board
    When it reads, adds, changes or deletes equipment or loans, or what is free
    Then the API refuses with a 403
    """
    response = getattr(client_of(UserFactory()), method)(path)

    assert response.status_code == 403
    assert response.json() == {"detail": "Accès réservé aux membres du bureau."}


# Availability


def test_a_member_reads_what_each_equipment_offers_over_a_period(board_client):
    """
    Given tables, and marquees of which one is under repair and two are lent
    When a member asks what is free over two days of that loan
    Then each equipment comes, by category, with what is taken, what remains,
    and the loan that takes it
    """
    marquees = EquipmentFactory(
        name="Barnums 3 × 3 m", repair_quantity=1, repair_note="Toile déchirée."
    )
    tables = EquipmentFactory(
        name="Tables pliantes 180 cm",
        category=EquipmentCategory.FURNITURE,
        storage_location="Local du comité · rack A",
        total_quantity=24,
        unit_value=None,
    )
    loan = lend(marquees, 2, ahead(15), ahead(17))

    response = board_client.get(AVAILABILITY, period(ahead(16), ahead(17)))

    assert response.status_code == 200
    assert response.json() == {
        "start": ahead(16).isoformat(),
        "end": ahead(17).isoformat(),
        "items": [
            {
                "equipment": {
                    "id": tables.id,
                    "name": "Tables pliantes 180 cm",
                    "category": "furniture",
                    "storage_location": "Local du comité · rack A",
                    "total_quantity": 24,
                    "repair_quantity": 0,
                    "unit_value": None,
                    "repair_note": "",
                },
                "taken": 0,
                "free": 24,
                "conflicts": [],
            },
            {
                "equipment": {
                    "id": marquees.id,
                    "name": "Barnums 3 × 3 m",
                    "category": "marquees",
                    "storage_location": "Garage communal",
                    "total_quantity": 4,
                    "repair_quantity": 1,
                    "unit_value": "250.00",
                    "repair_note": "Toile déchirée.",
                },
                "taken": 2,
                "free": 1,
                "conflicts": [
                    {
                        "loan": {
                            "id": loan.id,
                            "number": loan.number,
                            "display_name": "Club de football",
                            "purpose": "Tournoi jeunes",
                            "borrower_type": "association",
                            "state": "confirmed",
                            "start_date": ahead(15).isoformat(),
                            "end_date": ahead(17).isoformat(),
                        },
                        "quantity": 2,
                    }
                ],
            },
        ],
    }


def test_a_committee_loan_is_named_after_its_event(board_client):
    """
    Given marquees the committee keeps for its Halloween
    When a member asks what is free over those days
    Then the reservation in conflict has no number, and bears the event's title
    """
    marquees = EquipmentFactory()
    lend(marquees, 2, ahead(30), ahead(32), event=EventFactory(title="Halloween des enfants"))

    response = board_client.get(AVAILABILITY, period(ahead(30), ahead(30)))

    [conflict] = response.json()["items"][0]["conflicts"]
    assert {key: conflict["loan"][key] for key in ("number", "display_name", "state")} == {
        "number": None,
        "display_name": "Halloween des enfants",
        "state": "committee",
    }


def test_the_loan_being_edited_is_left_out(board_client):
    """
    Given marquees, two of them lent
    When a member edits that loan, and asks what is free over its days
    Then its own pieces do not stand in its way
    """
    marquees = EquipmentFactory()
    loan = lend(marquees, 2, ahead(15), ahead(17))

    response = board_client.get(
        AVAILABILITY, period(ahead(15), ahead(17)) | {"exclude_loan": loan.id}
    )

    [item] = response.json()["items"]
    assert (item["taken"], item["free"], item["conflicts"]) == (0, 4, [])


@pytest.mark.parametrize(
    ("query", "error"),
    [
        (
            period(ahead(17), ahead(15)),
            {
                "type": "validation_error",
                "loc": ["body"],
                "msg": "La date de retour est avant la date de sortie.",
            },
        ),
        (
            period(ahead(1), ahead(32)),
            {
                "type": "validation_error",
                "loc": ["body"],
                "msg": "Un prêt dure au plus 31 jours.",
            },
        ),
        (
            {"end": ahead(1).isoformat()},
            {"type": "missing", "loc": ["query", "start"], "msg": "Ce champ est obligatoire."},
        ),
        (
            {"start": "demain", "end": ahead(1).isoformat()},
            {
                "type": "date_from_datetime_parsing",
                "loc": ["query", "start"],
                "msg": "Saisissez une date valide.",
            },
        ),
    ],
)
def test_a_period_no_loan_could_cover_is_refused(board_client, query, error):
    """
    Given a period that ends before it starts, lasts 32 days, lacks its start,
    or starts on no date
    When a member asks what is free over it
    Then the API refuses with a 422, in French
    """
    response = board_client.get(AVAILABILITY, query)

    assert response.status_code == 422
    assert response.json() == {"detail": [error]}


def test_reading_what_is_free_takes_a_fixed_number_of_queries(
    board_client, django_assert_max_num_queries
):
    """
    Given five equipment, each lent twice, once to the committee
    When a member asks what is free over those days
    Then the loans and their events come in a fixed number of queries
    """
    for equipment in EquipmentFactory.create_batch(5):
        lend(equipment, 1, ahead(15), ahead(17))
        lend(equipment, 1, ahead(15), ahead(17), event=EventFactory())

    # Authentication (2), the equipment, the lines with their loans and events.
    with django_assert_max_num_queries(4):
        board_client.get(AVAILABILITY, period(ahead(15), ahead(17)))
