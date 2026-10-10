import datetime as dt

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from equipment.models import Equipment, EquipmentCategory, LoanStatus
from equipment.services.inventory import inventory
from tests.equipment.factories import EquipmentFactory, lend
from tests.equipment.mockup import TODAY, build_mockup
from tests.events.factories import EventFactory

pytestmark = pytest.mark.django_db

EQUIPMENT = "/api/board/equipment"


def url(equipment_id):
    return f"{EQUIPMENT}/{equipment_id}"


def ahead(days):
    return timezone.localdate() + dt.timedelta(days=days)


def payload(**changes):
    """An equipment as the inventory's form sends it, whole."""
    return {
        "name": "Barnums 3 × 6 m",
        "category": "marquees",
        "storage_location": "Garage communal",
        "total_quantity": 2,
        "repair_quantity": 0,
        "unit_value": "420.00",
        "repair_note": "",
    } | changes


def send(client, method, path, body):
    return getattr(client, method)(path, body, content_type="application/json")


def refusal(field, message):
    location = ["body", field] if field else ["body"]
    return {"detail": [{"type": "validation_error", "loc": location, "msg": message}]}


# Today's inventory


def test_the_inventory_of_the_mockup_tells_its_figures():
    """
    Given the equipment and the loans of the mockup, on 1 October
    When the inventory is read
    Then it counts 14 references, 3 partly taken today and 5 pieces under repair
    """
    build_mockup()

    totals = inventory(today=TODAY).totals

    assert (totals.references, totals.taken_today, totals.pieces_under_repair) == (14, 3, 5)


def test_a_member_reads_todays_inventory_by_category(board_client):
    """
    Given marquees, one under repair and two out today, tables the committee
    keeps for its event today, and chairs
    When a member reads the inventory
    Then each equipment comes by category with what is taken and free today,
    with the inventory's figures and the counts of its categories
    """
    marquees = EquipmentFactory(name="Barnums 3 × 3 m", repair_quantity=1)
    furniture = EquipmentCategory.FURNITURE
    tables = EquipmentFactory(name="Tables pliantes 180 cm", category=furniture, total_quantity=24)
    EquipmentFactory(name="Chaises empilables", category=furniture, total_quantity=80)
    lend(marquees, 2, ahead(-1), ahead(1), status=LoanStatus.OUT)
    lend(tables, 8, ahead(0), ahead(1), event=EventFactory())

    response = board_client.get(EQUIPMENT)

    assert response.status_code == 200
    body = response.json()
    assert body["day"] == timezone.localdate().isoformat()
    assert [(item["equipment"]["name"], item["taken"], item["free"]) for item in body["items"]] == [
        ("Chaises empilables", 0, 80),
        ("Tables pliantes 180 cm", 8, 16),
        ("Barnums 3 × 3 m", 2, 1),
    ]
    assert body["totals"] == {"references": 3, "taken_today": 2, "pieces_under_repair": 1}
    assert body["counts"] == {
        "total": 3,
        "furniture": 2,
        "marquees": 1,
        "sound_and_light": 0,
        "kitchen": 0,
        "street_and_games": 0,
    }


def test_the_inventory_takes_a_fixed_number_of_queries(board_client, django_assert_max_num_queries):
    """
    Given five equipment, each lent today
    When a member reads the inventory
    Then the loans come in a fixed number of queries
    """
    for equipment in EquipmentFactory.create_batch(5):
        lend(equipment, 1, ahead(0), ahead(2))

    # Authentication (2), the equipment, the lines with their loans and events.
    with django_assert_max_num_queries(4):
        board_client.get(EQUIPMENT)


# Adding


def test_a_member_adds_equipment(board_client):
    """
    Given a member of the board
    When they add two marquees of 3 × 6 m
    Then the equipment is recorded as they typed it
    """
    response = send(board_client, "post", EQUIPMENT, payload())

    assert response.status_code == 201
    assert response.json() == {"id": Equipment.objects.get().id} | payload()


@pytest.mark.parametrize(
    ("changes", "error"),
    [
        ({"name": "barnums 3 × 3 M"}, refusal(None, "Un matériel porte déjà ce nom.")),
        (
            {"total_quantity": 2, "repair_quantity": 3},
            refusal("repair_quantity", "La quantité en réparation dépasse la quantité totale."),
        ),
        (
            {"repair_quantity": -1},
            refusal(
                "repair_quantity", "Assurez-vous que cette valeur est supérieure ou égale à 0."
            ),
        ),
        (
            {"unit_value": "-5"},
            refusal("unit_value", "Assurez-vous que cette valeur est supérieure ou égale à 0."),
        ),
        ({"name": "  "}, refusal("name", "Ce champ ne peut pas être vide.")),
        (
            {"category": "tents"},
            {
                "detail": [
                    {
                        "type": "enum",
                        "loc": ["body", "payload", "category"],
                        "msg": "Sélectionnez un choix valide. Ce choix ne fait pas partie de "
                        "ceux disponibles.",
                    }
                ]
            },
        ),
    ],
)
def test_equipment_out_of_rule_is_refused(board_client, changes, error):
    """
    Given marquees of 3 × 3 m in the inventory
    When a member adds equipment of the same name whatever its case, with more
    pieces under repair than it has, a quantity or value below zero, no name,
    or a category the inventory does not know
    Then it is refused with a 422, in French
    """
    EquipmentFactory(name="Barnums 3 × 3 m")

    response = send(board_client, "post", EQUIPMENT, payload(**changes))

    assert response.status_code == 422
    assert response.json() == error


# Changing


def test_a_member_puts_pieces_back_in_service(board_client):
    """
    Given marquees, one of them under repair
    When a member puts it back in service and clears its repair note
    Then no piece is under repair any more
    """
    marquees = EquipmentFactory(repair_quantity=1, repair_note="Toile déchirée.")

    response = send(
        board_client,
        "put",
        url(marquees.id),
        payload(name=marquees.name, total_quantity=4, repair_quantity=0),
    )

    assert response.status_code == 200
    marquees.refresh_from_db()
    assert (marquees.repair_quantity, marquees.repair_note) == (0, "")


def test_a_piece_more_under_repair_is_refused_when_a_loan_would_lack_it(board_client):
    """
    Given 4 marquees, one under repair, and 3 lent for a tournament in a fortnight
    When a member puts a second one under repair
    Then it is refused under that quantity, naming the loan and its first day
    """
    marquees = EquipmentFactory(repair_quantity=1)
    lend(marquees, 3, ahead(15), ahead(17), number="P-2026-020")

    response = send(
        board_client,
        "put",
        url(marquees.id),
        payload(name=marquees.name, total_quantity=4, repair_quantity=2),
    )

    assert response.status_code == 422
    assert response.json() == refusal(
        "repair_quantity",
        f"Impossible : à partir du {ahead(15):%d/%m/%Y}, les prêts en prennent jusqu’à 3 "
        "(P-2026-020, Club de football), il n’en resterait que 2. Modifiez d’abord ce prêt.",
    )
    marquees.refresh_from_db()
    assert marquees.repair_quantity == 1


@pytest.mark.parametrize(
    ("total", "first_day", "remaining"),
    [(3, 16, "il n’en resterait que 3"), (0, 15, "il n’en resterait aucun")],
)
def test_a_lower_total_is_refused_when_loans_would_lack_pieces(
    board_client, total, first_day, remaining
):
    """
    Given 4 marquees, two lent from a fortnight ahead, two kept by the committee
    for its Halloween from the day after
    When a member lowers their total to 3, or to none
    Then it is refused under the total, from the first day short, with the most
    the loans take later on, naming both loans
    """
    marquees = EquipmentFactory()
    lend(marquees, 2, ahead(15), ahead(17), number="P-2026-020")
    lend(marquees, 2, ahead(16), ahead(18), event=EventFactory(title="Halloween des enfants"))

    response = send(
        board_client, "put", url(marquees.id), payload(name=marquees.name, total_quantity=total)
    )

    assert response.status_code == 422
    assert response.json() == refusal(
        "total_quantity",
        f"Impossible : à partir du {ahead(first_day):%d/%m/%Y}, les prêts en prennent jusqu’à 4 "
        f"(P-2026-020, Club de football ; Halloween des enfants), {remaining}. Modifiez d’abord "
        "ces prêts.",
    )


def test_a_change_that_takes_no_piece_away_passes_whatever_the_loans(board_client):
    """
    Given marquees already short: 2 offered, 3 lent, as a return may leave them
    When a member changes where they are stored
    Then it passes: the change takes no piece away
    """
    marquees = EquipmentFactory(total_quantity=3, repair_quantity=1)
    lend(marquees, 3, ahead(15), ahead(17))

    response = send(
        board_client,
        "put",
        url(marquees.id),
        payload(
            name=marquees.name,
            storage_location="Local du comité",
            total_quantity=3,
            repair_quantity=1,
        ),
    )

    assert response.status_code == 200
    assert response.json()["storage_location"] == "Local du comité"


def test_changing_equipment_locks_it_first(board_client):
    """
    Given marquees
    When a member changes them
    Then their row is locked first: a loan cannot read what is free in between
    """
    marquees = EquipmentFactory()

    with CaptureQueriesContext(connection) as queries:
        send(board_client, "put", url(marquees.id), payload(name=marquees.name))

    locks = [query["sql"] for query in queries.captured_queries if "FOR UPDATE" in query["sql"]]
    assert len(locks) == 1
    assert Equipment._meta.db_table in locks[0]


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("put", url(999), payload()),
        ("delete", url(999), None),
        ("get", f"{url(999)}/occupancy", None),
    ],
)
def test_unknown_equipment_is_not_found(board_client, method, path, body):
    """
    Given no equipment of that id
    When a member changes it, deletes it, or reads its occupancy
    Then the API answers with a 404
    """
    response = send(board_client, method, path, body)

    assert response.status_code == 404
    assert response.json() == {"detail": "Introuvable."}


# Deleting


def test_a_member_deletes_equipment_never_lent(board_client):
    """
    Given marquees never lent
    When a member deletes them
    Then they leave the inventory
    """
    marquees = EquipmentFactory()

    response = board_client.delete(url(marquees.id))

    assert response.status_code == 204
    assert not Equipment.objects.exists()


@pytest.mark.parametrize(("loans", "count"), [(1, "1 prêt"), (2, "2 prêts")])
def test_lent_equipment_cannot_be_deleted(board_client, loans, count):
    """
    Given marquees lent once, or twice
    When a member deletes them
    Then it is refused, naming how many loans keep them in their history
    """
    marquees = EquipmentFactory(name="Barnums 3 × 3 m")
    for _ in range(loans):
        lend(
            marquees,
            1,
            ahead(-20),
            ahead(-18),
            status=LoanStatus.RETURNED,
            returned_at=timezone.now(),
        )

    response = board_client.delete(url(marquees.id))

    assert response.status_code == 422
    assert response.json() == refusal(
        None, f"Impossible de supprimer « Barnums 3 × 3 m » : il figure dans {count}."
    )
    assert Equipment.objects.exists()


# Occupancy


def test_the_occupancy_covers_eleven_weeks_from_this_monday(board_client):
    """
    Given marquees lent this week, kept for Halloween, returned last week, and
    lent beyond eleven weeks
    When a member reads their occupancy
    Then it runs from this Monday for eleven weeks, with the loans that hold
    them in it, the first to start first
    """
    today = timezone.localdate()
    monday = today - dt.timedelta(days=today.weekday())
    marquees = EquipmentFactory()
    this_week = lend(marquees, 1, monday, monday + dt.timedelta(days=2))
    kept = lend(
        marquees, 2, ahead(30), ahead(31), event=EventFactory(title="Halloween des enfants")
    )
    lend(
        marquees,
        1,
        monday - dt.timedelta(days=7),
        monday - dt.timedelta(days=5),
        status=LoanStatus.RETURNED,
        returned_at=timezone.now(),
    )
    lend(marquees, 1, monday + dt.timedelta(days=77), monday + dt.timedelta(days=78))

    response = board_client.get(f"{url(marquees.id)}/occupancy")

    assert response.status_code == 200
    body = response.json()
    assert (body["start"], body["end"]) == (
        monday.isoformat(),
        (monday + dt.timedelta(days=76)).isoformat(),
    )
    assert [(conflict["loan"]["id"], conflict["quantity"]) for conflict in body["loans"]] == [
        (this_week.id, 1),
        (kept.id, 2),
    ]
    assert body["loans"][1]["loan"]["display_name"] == "Halloween des enfants"
