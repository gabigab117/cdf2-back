import datetime as dt

import pytest
from django.utils import timezone

from equipment.models import Equipment, LoanStatus
from tests.equipment.factories import CommitteeLoanFactory, EquipmentFactory, LoanLineFactory, lend

pytestmark = pytest.mark.django_db

LOANS = "/api/board/loans"


def url(loan_id, action):
    return f"{LOANS}/{loan_id}/{action}"


def ahead(days):
    return timezone.localdate() + dt.timedelta(days=days)


def form_refusal(*messages):
    return {
        "detail": [
            {"type": "validation_error", "loc": ["body"], "msg": message} for message in messages
        ]
    }


def send(client, path, body=None):
    return (
        client.post(path, body, content_type="application/json")
        if body is not None
        else client.post(path)
    )


@pytest.fixture
def marquees():
    return EquipmentFactory(
        name="Barnums 3 × 3 m", repair_quantity=1, repair_note="Toile déchirée."
    )


# Checkout


def test_a_confirmed_loan_is_handed_over(board_client, marquees):
    """
    Given a loan of two marquees, confirmed, starting today
    When a member hands its equipment over
    Then it is out
    """
    loan = lend(marquees, 2, ahead(0), ahead(2))

    response = send(board_client, url(loan.id, "checkout"))

    assert response.status_code == 200
    assert (response.json()["status"], response.json()["state"]) == ("out", "out")


def test_a_loan_handed_over_early_is_refused_if_its_pieces_are_still_taken(board_client, marquees):
    """
    Given three marquees free, two of them out until tomorrow, and a loan of two
    starting in three days
    When a member hands that loan over today
    Then it is refused: its pieces are still taken, and it stays confirmed
    """
    lend(marquees, 2, ahead(-2), ahead(1), status=LoanStatus.OUT)
    loan = lend(marquees, 2, ahead(3), ahead(5))

    response = send(board_client, url(loan.id, "checkout"))

    assert response.status_code == 422
    assert response.json() == form_refusal(
        "Le matériel de ce prêt n’est pas libre sur ses jours :",
        "Barnums 3 × 3 m : 2 demandés, 1 libre sur la période.",
    )
    loan.refresh_from_db()
    assert loan.status == LoanStatus.CONFIRMED


@pytest.mark.parametrize(
    ("committee", "message"),
    [
        (True, "Un usage comité ne sort pas : il reste confirmé jusqu’à son événement."),
        (False, "Ce prêt n’est pas confirmé : il ne peut pas sortir."),
    ],
)
def test_a_committee_loan_or_one_out_is_not_handed_over(board_client, marquees, committee, message):
    """
    Given the equipment the committee keeps, or a loan out already
    When a member hands it over
    Then it is refused
    """
    out = lend(marquees, 1, ahead(-2), ahead(1), status=LoanStatus.OUT)
    loan = CommitteeLoanFactory() if committee else out

    response = send(board_client, url(loan.id, "checkout"))

    assert response.status_code == 422
    assert response.json() == form_refusal(message)


# Return (A17)


def test_a_return_puts_the_damaged_pieces_under_repair(board_client, marquees):
    """
    Given a loan P-2026-018 out, of two marquees and four tables
    When a member records the return, a marquee damaged and a table missing
    Then the marquee goes under repair, its note telling why; the table is
    reported, the stock left as it is; the loan is returned, dated
    """
    tables = EquipmentFactory(name="Tables pliantes 180 cm", total_quantity=24)
    loan = lend(marquees, 2, ahead(-3), ahead(0), status=LoanStatus.OUT, number="P-2026-018")
    marquee_line = loan.lines.get()
    table_line = LoanLineFactory(loan=loan, equipment=tables, quantity=4)

    response = send(
        board_client,
        url(loan.id, "return"),
        {
            "lines": [
                {"line": marquee_line.id, "damaged_quantity": 1, "missing_quantity": 0},
                {"line": table_line.id, "damaged_quantity": 0, "missing_quantity": 1},
            ]
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert (body["loan"]["status"], body["loan"]["state"], body["shortages"]) == (
        "returned",
        "returned",
        [],
    )
    assert body["loan"]["returned_at"] is not None
    assert [
        (line["equipment"]["name"], line["damaged_quantity"], line["missing_quantity"])
        for line in body["loan"]["lines"]
    ] == [("Barnums 3 × 3 m", 1, 0), ("Tables pliantes 180 cm", 0, 1)]
    marquees.refresh_from_db()
    tables.refresh_from_db()
    assert (marquees.repair_quantity, marquees.repair_note) == (
        2,
        "Toile déchirée.\n1 abîmé au retour du prêt P-2026-018.",
    )
    assert (tables.total_quantity, tables.repair_quantity) == (24, 0)


def test_a_return_names_the_loans_its_repairs_leave_short(board_client, marquees):
    """
    Given 4 marquees, one under repair, two out, and a loan of three for a
    tournament in a fortnight
    When the two out come back damaged
    Then the return is recorded, and names the tournament's loan, short from its start
    """
    loan = lend(marquees, 2, ahead(-3), ahead(0), status=LoanStatus.OUT)
    tournament = lend(marquees, 3, ahead(15), ahead(17), number="P-2026-020")

    response = send(
        board_client,
        url(loan.id, "return"),
        {"lines": [{"line": loan.lines.get().id, "damaged_quantity": 2, "missing_quantity": 0}]},
    )

    assert response.status_code == 200
    [shortage] = response.json()["shortages"]
    assert shortage["equipment"] == {
        "id": marquees.id,
        "name": "Barnums 3 × 3 m",
        "unit_value": "250.00",
    }
    assert (shortage["day"], shortage["offered"], shortage["taken"]) == (
        ahead(15).isoformat(),
        1,
        3,
    )
    assert [(item["id"], item["number"], item["state"]) for item in shortage["loans"]] == [
        (tournament.id, "P-2026-020", "confirmed")
    ]


def test_damaged_pieces_never_put_more_under_repair_than_the_total(board_client):
    """
    Given two benches, both under repair already, then lent anyway
    When they come back damaged
    Then no more than the two benches are under repair
    """
    benches = EquipmentFactory(name="Bancs pliants", total_quantity=2, repair_quantity=2)
    loan = lend(benches, 2, ahead(-3), ahead(0), status=LoanStatus.OUT)

    send(
        board_client,
        url(loan.id, "return"),
        {"lines": [{"line": loan.lines.get().id, "damaged_quantity": 2, "missing_quantity": 0}]},
    )

    benches.refresh_from_db()
    assert benches.repair_quantity == 2


@pytest.mark.parametrize(
    ("counted", "error"),
    [
        (
            {"damaged_quantity": 2, "missing_quantity": 1},
            (["lines", 0], "Les pièces abîmées et manquantes dépassent la quantité prêtée."),
        ),
        (
            {"damaged_quantity": -1, "missing_quantity": 0},
            (
                ["lines", 0, "damaged_quantity"],
                "Assurez-vous que cette valeur est supérieure ou égale à 0.",
            ),
        ),
    ],
)
def test_a_return_beyond_what_was_lent_is_refused(board_client, marquees, counted, error):
    """
    Given a loan of two marquees out
    When its return counts three damaged or missing, or fewer than none
    Then it is refused under the line, and the loan stays out
    """
    loan = lend(marquees, 2, ahead(-3), ahead(0), status=LoanStatus.OUT)

    response = send(
        board_client, url(loan.id, "return"), {"lines": [{"line": loan.lines.get().id, **counted}]}
    )

    assert response.status_code == 422
    location, message = error
    assert response.json() == {
        "detail": [{"type": "validation_error", "loc": ["body", *location], "msg": message}]
    }
    loan.refresh_from_db()
    assert loan.status == LoanStatus.OUT


def test_a_return_names_only_the_loans_own_lines_once(board_client, marquees):
    """
    Given a loan out, and the line of another loan
    When its return counts the other loan's line, then its own twice
    Then each wrong line is refused under its position
    """
    loan = lend(marquees, 2, ahead(-3), ahead(0), status=LoanStatus.OUT)
    other = LoanLineFactory()
    own = loan.lines.get().id

    response = send(
        board_client,
        url(loan.id, "return"),
        {
            "lines": [
                {"line": other.id, "damaged_quantity": 0, "missing_quantity": 0},
                {"line": own, "damaged_quantity": 0, "missing_quantity": 0},
                {"line": own, "damaged_quantity": 1, "missing_quantity": 0},
            ]
        },
    )

    message = "Cette ligne n’appartient pas au prêt, ou figure deux fois."
    assert response.status_code == 422
    assert response.json() == {
        "detail": [
            {"type": "validation_error", "loc": ["body", "lines", 0, "line"], "msg": message},
            {"type": "validation_error", "loc": ["body", "lines", 2, "line"], "msg": message},
        ]
    }


def test_a_loan_not_out_is_not_returned(board_client, marquees):
    """
    Given a confirmed loan
    When a member records its return
    Then it is refused
    """
    loan = lend(marquees, 1, ahead(3), ahead(4))

    response = send(board_client, url(loan.id, "return"), {"lines": []})

    assert response.status_code == 422
    assert response.json() == form_refusal("Ce prêt n’est pas sorti : il ne peut pas être rendu.")


# Reopening


def test_reopening_a_loan_undoes_its_return(board_client, marquees):
    """
    Given a loan returned with a marquee damaged, its mention in the note
    When a member reopens it
    Then the marquee leaves the repairs, the mention leaves the note, the
    counts of the return are cleared, and the loan is out again
    """
    loan = lend(marquees, 2, ahead(-3), ahead(0), status=LoanStatus.OUT, number="P-2026-018")
    send(
        board_client,
        url(loan.id, "return"),
        {"lines": [{"line": loan.lines.get().id, "damaged_quantity": 1, "missing_quantity": 1}]},
    )

    response = send(board_client, url(loan.id, "reopen"))

    assert response.status_code == 200
    assert (response.json()["status"], response.json()["returned_at"]) == ("out", None)
    assert response.json()["lines"][0]["damaged_quantity"] == 0
    assert response.json()["lines"][0]["missing_quantity"] == 0
    marquees.refresh_from_db()
    assert (marquees.repair_quantity, marquees.repair_note) == (1, "Toile déchirée.")


def test_reopening_leaves_a_note_rewritten_since_and_never_goes_below_no_repair(board_client):
    """
    Given a loan returned with two benches damaged, both mended since, and the
    note rewritten
    When a member reopens it
    Then none is under repair, rather than less than none, and the note stays
    """
    benches = EquipmentFactory(name="Bancs pliants", total_quantity=10)
    loan = lend(
        benches,
        2,
        ahead(-3),
        ahead(-1),
        status=LoanStatus.RETURNED,
        returned_at=timezone.now(),
        number="P-2026-019",
    )
    loan.lines.update(damaged_quantity=2)
    Equipment.objects.filter(pk=benches.pk).update(repair_note="Réparés le 5 octobre.")

    response = send(board_client, url(loan.id, "reopen"))

    assert response.status_code == 200
    benches.refresh_from_db()
    assert (benches.repair_quantity, benches.repair_note) == (0, "Réparés le 5 octobre.")


def test_a_loan_whose_pieces_were_lent_again_is_not_reopened(board_client, marquees):
    """
    Given a loan of three marquees returned yesterday, and the three lent again today
    When a member reopens the first
    Then it is refused: its pieces are taken, and it stays returned
    """
    loan = lend(
        marquees, 3, ahead(-3), ahead(-1), status=LoanStatus.RETURNED, returned_at=timezone.now()
    )
    lend(marquees, 3, ahead(0), ahead(2))

    response = send(board_client, url(loan.id, "reopen"))

    assert response.status_code == 422
    assert response.json() == form_refusal(
        "Le matériel de ce prêt n’est pas libre sur ses jours :",
        "Barnums 3 × 3 m : 3 demandés, 0 libre sur la période.",
    )
    loan.refresh_from_db()
    assert loan.status == LoanStatus.RETURNED


def test_a_loan_not_returned_is_not_reopened(board_client, marquees):
    loan = lend(marquees, 1, ahead(3), ahead(4))

    response = send(board_client, url(loan.id, "reopen"))

    assert response.status_code == 422
    assert response.json() == form_refusal("Ce prêt n’est pas rendu : il ne peut pas être rouvert.")


# Cancelling


@pytest.mark.parametrize("committee", [False, True])
def test_a_confirmed_loan_is_cancelled_the_committees_included(board_client, marquees, committee):
    """
    Given a confirmed loan, or the equipment kept for an event
    When a member cancels it
    Then it is cancelled, and its pieces are free again
    """
    loan = CommitteeLoanFactory() if committee else lend(marquees, 2, ahead(3), ahead(4))

    response = send(board_client, url(loan.id, "cancel"))

    assert response.status_code == 200
    assert (response.json()["status"], response.json()["state"]) == ("cancelled", "cancelled")


def test_a_loan_out_is_not_cancelled(board_client, marquees):
    loan = lend(marquees, 1, ahead(-1), ahead(1), status=LoanStatus.OUT)

    response = send(board_client, url(loan.id, "cancel"))

    assert response.status_code == 422
    assert response.json() == form_refusal(
        "Seul un prêt confirmé s’annule : un prêt sorti se rend."
    )


@pytest.mark.parametrize("action", ["checkout", "return", "reopen", "cancel"])
def test_an_unknown_loan_is_not_found(board_client, action):
    response = send(board_client, url(999, action), {"lines": []} if action == "return" else None)

    assert response.status_code == 404
