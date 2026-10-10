import datetime as dt

import pytest
from django.core.serializers.json import DjangoJSONEncoder
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from equipment.models import Equipment, Loan, LoanLine, LoanNumberSequence, LoanStatus
from tests.documents.factories import DocumentFactory
from tests.equipment.factories import (
    CommitteeLoanFactory,
    EquipmentFactory,
    LoanFactory,
    LoanLineFactory,
    lend,
)
from tests.events.factories import EventFactory

pytestmark = pytest.mark.django_db

LOANS = "/api/board/loans"


def url(loan_id):
    return f"{LOANS}/{loan_id}"


def ahead(days):
    return timezone.localdate() + dt.timedelta(days=days)


def iso(moment):
    """A time as the API writes it: to the millisecond, as Django's JSON does."""
    return DjangoJSONEncoder().default(moment)


def payload(*lines, **changes):
    """A loan as the form sends it, whole: an association, in a fortnight."""
    return {
        "borrower_type": "association",
        "borrower_name": "Club de football",
        "purpose": "Tournoi jeunes",
        "phone": "01 23 45 67 89",
        "start_date": ahead(15).isoformat(),
        "end_date": ahead(17).isoformat(),
        "deposit_amount": None,
        "event": None,
        "notes": "",
        "lines": [
            {"equipment": equipment.id, "quantity": quantity} for equipment, quantity in lines
        ],
    } | changes


def send(client, method, path, body):
    return getattr(client, method)(path, body, content_type="application/json")


def refusal(*errors):
    """A 422 holding errors located under their fields, or under the form for None."""
    return {
        "detail": [
            {"type": "validation_error", "loc": ["body", *location], "msg": message}
            for location, message in errors
        ]
    }


@pytest.fixture
def marquees():
    return EquipmentFactory(name="Barnums 3 × 3 m", repair_quantity=1)


# Recording


def test_a_member_records_a_loan_to_an_association(board_client, board_member, marquees):
    """
    Given marquees, three of them free
    When a member lends two to the football club, without a deposit typed
    Then the loan is the first of the year, confirmed, with the association's
    deposit, and leads with its lines and author
    """
    response = send(board_client, "post", LOANS, payload((marquees, 2)))

    assert response.status_code == 201
    loan = Loan.objects.get()
    line = loan.lines.get()
    year = timezone.localdate().year
    assert response.json() == {
        "id": loan.id,
        "number": f"P-{year}-001",
        "borrower_type": "association",
        "borrower_name": "Club de football",
        "display_name": "Club de football",
        "purpose": "Tournoi jeunes",
        "phone": "01 23 45 67 89",
        "start_date": ahead(15).isoformat(),
        "end_date": ahead(17).isoformat(),
        "status": "confirmed",
        "state": "confirmed",
        "deposit_amount": "150.00",
        "event": None,
        "notes": "",
        "lines": [
            {
                "id": line.id,
                "equipment": {"id": marquees.id, "name": "Barnums 3 × 3 m", "unit_value": "250.00"},
                "quantity": 2,
                "damaged_quantity": 0,
                "missing_quantity": 0,
            }
        ],
        "created_by": {
            "id": board_member.id,
            "first_name": board_member.first_name,
            "last_name": board_member.last_name,
            "email": board_member.email,
        },
        "created_at": iso(loan.created_at),
        "returned_at": None,
        "agreement": None,
    }


@pytest.mark.parametrize(
    ("kind", "typed", "deposit"),
    [
        ("individual", None, "300.00"),
        ("municipality", None, "0.00"),
        ("association", "80.00", "80.00"),
    ],
)
def test_a_deposit_comes_from_the_borrowers_type_unless_typed(
    board_client, marquees, kind, typed, deposit
):
    """
    Given a person, the municipality, or an association that leaves 80 €
    When a member lends them marquees
    Then the deposit is the type's own, unless the member typed another
    """
    response = send(
        board_client,
        "post",
        LOANS,
        payload((marquees, 1), borrower_type=kind, deposit_amount=typed),
    )

    assert response.status_code == 201
    assert response.json()["deposit_amount"] == deposit


def test_the_loans_of_a_year_are_numbered_in_sequence(board_client, marquees):
    """
    Given the 41st loan of this year recorded, and a counter of last year
    When a member records two loans, then the equipment of an event
    Then the loans take the numbers 42 and 43 of this year; the event's has none
    """
    year = timezone.localdate().year
    LoanNumberSequence.objects.create(year=year, last_number=41)
    LoanNumberSequence.objects.create(year=year - 1, last_number=97)

    numbers = [
        send(board_client, "post", LOANS, payload((marquees, 1))).json()["number"] for _ in range(2)
    ]
    committee = send(
        board_client,
        "post",
        LOANS,
        payload((marquees, 1), borrower_type="committee", event=EventFactory().id),
    ).json()

    assert numbers == [f"P-{year}-042", f"P-{year}-043"]
    assert committee["number"] is None
    assert LoanNumberSequence.objects.get(year=year - 1).last_number == 97


def test_the_first_loan_of_a_year_starts_its_counter(board_client, marquees):
    """
    Given no loan recorded this year
    When a member records one
    Then the counter of the year starts, at one
    """
    send(board_client, "post", LOANS, payload((marquees, 1)))

    assert LoanNumberSequence.objects.get().last_number == 1


def test_the_committee_keeps_equipment_for_its_event(board_client, marquees):
    """
    Given Halloween, an event of the committee
    When a member keeps marquees for it, a borrower, phone and deposit typed
    Then the reservation is named after the event, without number, borrower,
    phone nor deposit
    """
    event = EventFactory(title="Halloween des enfants")

    response = send(
        board_client,
        "post",
        LOANS,
        payload((marquees, 2), borrower_type="committee", event=event.id, deposit_amount="150.00"),
    )

    assert response.status_code == 201
    body = response.json()
    assert {
        key: body[key] for key in ("number", "borrower_name", "display_name", "purpose", "phone")
    } == {
        "number": None,
        "borrower_name": "",
        "display_name": "Halloween des enfants",
        "purpose": "",
        "phone": "",
    }
    assert (body["deposit_amount"], body["state"]) == ("0.00", "committee")
    assert body["event"] == {"id": event.id, "title": "Halloween des enfants"}


@pytest.mark.parametrize(
    ("changes", "errors"),
    [
        ({"borrower_name": ""}, [(["borrower_name"], "Ce champ ne peut pas être vide.")]),
        (
            {"borrower_type": "committee"},
            [(["event"], "Choisissez l’événement du comité.")],
        ),
        (
            {"borrower_type": "committee", "event": 999},
            [(["event"], "Choisissez un événement existant.")],
        ),
        (
            {"end_date": ahead(14).isoformat()},
            [(["end_date"], "La date de retour est avant la date de sortie.")],
        ),
        (
            {"end_date": ahead(46).isoformat()},
            [(["end_date"], "Un prêt dure au plus 31 jours.")],
        ),
        ({"lines": []}, [([], "Ajoutez au moins un matériel.")]),
        (
            {"lines": [{"equipment": 999, "quantity": 1}]},
            [(["lines", 0, "equipment"], "Choisissez un matériel existant.")],
        ),
        (
            {"deposit_amount": "-5"},
            [(["deposit_amount"], "Assurez-vous que cette valeur est supérieure ou égale à 0.")],
        ),
    ],
)
def test_a_loan_out_of_rule_is_refused(board_client, marquees, changes, errors):
    """
    Given marquees
    When a member records a loan without a borrower, the committee's without
    its event or for no event, a loan that ends before it starts or lasts 46
    days, one without equipment or of unknown equipment, or a negative deposit
    Then it is refused with a 422, under the field at fault, and nothing is written
    """
    response = send(board_client, "post", LOANS, payload((marquees, 1), **changes))

    assert response.status_code == 422
    assert response.json() == refusal(*errors)
    assert not Loan.objects.exists()


def test_each_line_of_a_loan_is_checked(board_client, marquees):
    """
    Given marquees and tables
    When a member lends no marquee, and tables twice
    Then each line is refused under its position, every error at once
    """
    tables = EquipmentFactory(name="Tables pliantes 180 cm", total_quantity=24)

    response = send(board_client, "post", LOANS, payload((marquees, 0), (tables, 2), (tables, 1)))

    assert response.status_code == 422
    assert response.json() == refusal(
        (["lines", 0, "quantity"], "Assurez-vous que cette valeur est supérieure ou égale à 1."),
        (["lines", 2, "equipment"], "Ce matériel figure déjà dans le prêt."),
    )


# What is free (A15)


def test_a_loan_beyond_what_is_free_is_refused_line_by_line(board_client, marquees):
    """
    Given 4 marquees, one under repair, two lent for the tournament, and 3 tables
    When a member lends 2 marquees and 4 tables over the tournament's days
    Then each line beyond is refused under its quantity, telling what is free
    """
    tables = EquipmentFactory(name="Tables pliantes 180 cm", total_quantity=3)
    lend(marquees, 2, ahead(15), ahead(17))

    response = send(board_client, "post", LOANS, payload((marquees, 2), (tables, 4)))

    assert response.status_code == 422
    assert response.json() == refusal(
        (["lines", 0, "quantity"], "Barnums 3 × 3 m : 2 demandés, 1 libre sur la période."),
        (["lines", 1, "quantity"], "Tables pliantes 180 cm : 4 demandés, 3 libres sur la période."),
    )
    assert Loan.objects.count() == 1


def test_the_loan_being_edited_keeps_its_own_pieces(board_client, marquees):
    """
    Given a loan of the three marquees free, and a member editing it
    When its days and lines are sent again, its notes changed
    Then it passes: its own pieces are not counted against it
    """
    loan = send(board_client, "post", LOANS, payload((marquees, 3))).json()

    response = send(
        board_client, "put", url(loan["id"]), payload((marquees, 3), notes="Clés au local.")
    )

    assert response.status_code == 200
    assert response.json()["notes"] == "Clés au local."
    assert response.json()["number"] == loan["number"]


def test_a_late_loan_is_checked_until_today(board_client, marquees):
    """
    Given a marquee out since last week, due back yesterday, and two lent to
    others from today
    When a member edits that late loan, its days kept, two pieces asked
    Then it is refused: still out, it holds its pieces until today (A15)
    """
    late = lend(marquees, 1, ahead(-7), ahead(-1), status=LoanStatus.OUT)
    lend(marquees, 2, ahead(0), ahead(2))

    response = send(
        board_client,
        "put",
        url(late.id),
        payload((marquees, 2), start_date=ahead(-7).isoformat(), end_date=ahead(-1).isoformat()),
    )

    assert response.status_code == 422
    assert response.json() == refusal(
        (["lines", 0, "quantity"], "Barnums 3 × 3 m : 2 demandés, 1 libre sur la période."),
    )


# Changing


def test_a_member_changes_a_loan_its_lines_replaced(board_client, marquees):
    """
    Given a loan of two marquees
    When a member changes it to one marquee and six tables, another day
    Then its lines are replaced, its number kept
    """
    tables = EquipmentFactory(name="Tables pliantes 180 cm", total_quantity=24)
    loan = send(board_client, "post", LOANS, payload((marquees, 2))).json()

    response = send(
        board_client,
        "put",
        url(loan["id"]),
        payload((marquees, 1), (tables, 6), end_date=ahead(16).isoformat()),
    )

    assert response.status_code == 200
    body = response.json()
    assert [(line["equipment"]["name"], line["quantity"]) for line in body["lines"]] == [
        ("Barnums 3 × 3 m", 1),
        ("Tables pliantes 180 cm", 6),
    ]
    assert (body["number"], body["end_date"]) == (loan["number"], ahead(16).isoformat())
    assert LoanLine.objects.count() == 2


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (LoanStatus.RETURNED, "Ce prêt est rendu : rouvrez-le avant de le modifier."),
        (LoanStatus.CANCELLED, "Ce prêt est annulé : il ne se modifie plus."),
    ],
)
def test_a_loan_returned_or_cancelled_is_no_longer_changed(board_client, marquees, status, message):
    """
    Given a loan returned, or cancelled
    When a member changes it
    Then it is refused
    """
    returned_at = timezone.now() if status == LoanStatus.RETURNED else None
    loan = lend(marquees, 1, ahead(-5), ahead(-3), status=status, returned_at=returned_at)

    response = send(board_client, "put", url(loan.id), payload((marquees, 1)))

    assert response.status_code == 422
    assert response.json() == refusal(([], message))


@pytest.mark.parametrize("committee_first", [True, False])
def test_a_committee_loan_never_becomes_a_loan_to_someone(board_client, marquees, committee_first):
    """
    Given the equipment kept for an event, or a loan to someone
    When a member changes it to the other kind
    Then it is refused under the type of borrower
    """
    event = EventFactory()
    loan = CommitteeLoanFactory(event=event) if committee_first else LoanFactory()
    changes = {} if committee_first else {"borrower_type": "committee", "event": event.id}

    response = send(board_client, "put", url(loan.id), payload((marquees, 1), **changes))

    assert response.status_code == 422
    assert response.json() == refusal(
        (["borrower_type"], "Un usage comité ne devient pas un prêt à un tiers, ni l’inverse.")
    )


def test_an_event_keeps_a_single_reservation(board_client, marquees):
    """
    Given Halloween, its equipment kept already
    When a member keeps more for it in a second reservation
    Then it is refused under the event
    """
    event = EventFactory()
    CommitteeLoanFactory(event=event)

    response = send(
        board_client,
        "post",
        LOANS,
        payload((marquees, 1), borrower_type="committee", event=event.id),
    )

    assert response.status_code == 422
    assert response.json() == refusal(
        (["event"], "Cet événement a déjà sa réservation de matériel.")
    )


# Locks


def test_recording_a_loan_locks_its_equipment_then_the_counter(board_client, marquees):
    """
    Given marquees and tables
    When a member lends both
    Then their rows are locked in the order of their keys, then the counter of
    the year: two loans at once cannot both take the last pieces, nor a number
    """
    tables = EquipmentFactory(name="Tables pliantes 180 cm", total_quantity=24)

    with CaptureQueriesContext(connection) as queries:
        send(board_client, "post", LOANS, payload((tables, 1), (marquees, 1)))

    locks = [query["sql"] for query in queries.captured_queries if "FOR UPDATE" in query["sql"]]
    assert len(locks) == 2
    assert Equipment._meta.db_table in locks[0]
    assert 'ORDER BY "equipment_equipment"."id" ASC' in locks[0]
    assert LoanNumberSequence._meta.db_table in locks[1]


def test_changing_a_loan_locks_it_then_its_old_and_new_equipment(board_client, marquees):
    """
    Given a loan of marquees
    When a member changes it to tables
    Then the loan is locked first, then both the marquees it gives back and the
    tables it takes
    """
    tables = EquipmentFactory(name="Tables pliantes 180 cm", total_quantity=24)
    loan = lend(marquees, 1, ahead(15), ahead(17))

    with CaptureQueriesContext(connection) as queries:
        send(board_client, "put", url(loan.id), payload((tables, 1)))

    locks = [query["sql"] for query in queries.captured_queries if "FOR UPDATE" in query["sql"]]
    assert len(locks) == 2
    assert Loan._meta.db_table in locks[0]
    assert str(marquees.id) in locks[1]
    assert str(tables.id) in locks[1]


# Reading


def test_a_member_reads_a_loan(board_client, marquees):
    """
    Given a loan of marquees, out since yesterday and due back yesterday
    When a member reads it
    Then it comes whole, overdue
    """
    loan = lend(marquees, 2, ahead(-3), ahead(-1), status=LoanStatus.OUT)

    response = board_client.get(url(loan.id))

    assert response.status_code == 200
    assert (response.json()["state"], response.json()["lines"][0]["quantity"]) == ("overdue", 2)


@pytest.mark.parametrize(
    "lent",
    [CommitteeLoanFactory, lambda: LoanFactory(agreement=DocumentFactory())],
    ids=["committee loan", "loan with its agreement"],
)
def test_reading_a_loan_takes_a_fixed_number_of_queries(
    board_client, django_assert_max_num_queries, lent
):
    """
    Given the equipment an event keeps, or a loan with its signed agreement,
    five lines of each
    When a member reads it
    Then its event or agreement, author and lines come in a fixed number of queries
    """
    loan = lent()
    LoanLineFactory.create_batch(5, loan=loan)

    # Authentication (2), the loan with its event, author and agreement, its
    # lines with their equipment.
    with django_assert_max_num_queries(4):
        board_client.get(url(loan.id))


@pytest.mark.parametrize(("method", "body"), [("get", None), ("put", {})])
def test_an_unknown_loan_is_not_found(board_client, marquees, method, body):
    """
    Given no loan of that id
    When a member reads or changes it
    Then the API answers with a 404
    """
    response = send(
        board_client, method, url(999), payload((marquees, 1)) if body is not None else None
    )

    assert response.status_code == 404


def test_a_member_reads_the_default_deposits(board_client):
    """
    Given the deposits of A16
    When a member reads them, for the form of a loan
    Then each type of borrower comes with its own
    """
    response = board_client.get(f"{LOANS}/deposits")

    assert response.status_code == 200
    assert response.json() == {
        "deposits": [
            {"borrower_type": "association", "amount": "150.00"},
            {"borrower_type": "individual", "amount": "300.00"},
            {"borrower_type": "municipality", "amount": "0.00"},
            {"borrower_type": "committee", "amount": "0.00"},
        ]
    }
