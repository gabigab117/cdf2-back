import datetime as dt

import pytest

from tests.accounts.factories import BoardMemberFactory, UserFactory, client_of
from tests.documents.factories import DocumentFactory
from tests.events.factories import EventFactory
from tests.helpers import ahead, iso, member_json, send
from tests.treasury.factories import AdvanceFactory, IncomeFactory, LedgerEntryFactory
from treasury.models import LedgerEntry, ReimbursementMethod

pytestmark = pytest.mark.django_db

TREASURY = "/api/board/treasury"
ENTRIES = f"{TREASURY}/entries"

# Every operation of the treasury, the paths of a single entry naming any id: a
# refusal comes before the entry is looked up.
OPERATIONS = [
    ("get", f"{TREASURY}/results?year=2026"),
    ("get", f"{TREASURY}/report?year=2026"),
    ("get", ENTRIES),
    ("post", ENTRIES),
    ("get", f"{ENTRIES}/1"),
    ("put", f"{ENTRIES}/1"),
    ("delete", f"{ENTRIES}/1"),
    ("post", f"{ENTRIES}/1/receipt"),
    ("post", f"{ENTRIES}/1/reimbursement"),
    ("delete", f"{ENTRIES}/1/reimbursement"),
    ("post", f"{TREASURY}/invoices/1/expense"),
    ("post", f"{TREASURY}/invoices/1/attach"),
]


def entry_url(entry_id):
    return f"{ENTRIES}/{entry_id}"


def form(**changes):
    """The fields of an expense, as the journal's form sends them: a field left
    empty is not sent.
    """
    fields = {
        "date": "2026-09-12",
        "kind": "expense",
        "label": "Courses buvette",
        "amount": "286.30",
        "category": "drinks",
        "payment_method": "association_card",
    } | changes
    return {name: value for name, value in fields.items() if value is not None}


def whole(entry, **changes):
    """The JSON body of an entry, whole, as its correction sends it."""
    return {
        "date": entry.date.isoformat(),
        "kind": entry.kind,
        "label": entry.label,
        "amount": str(entry.amount),
        "category": entry.category,
        "payment_method": entry.payment_method,
        "advanced_by": entry.advanced_by_id,
        "event": entry.event_id,
        "supplier": entry.supplier,
        "note": entry.note,
    } | changes


def correct(client, entry, **changes):
    return send(client, "put", entry_url(entry.pk), whole(entry, **changes))


def field_errors(response):
    """The messages of a 422, by field, wherever the request placed them."""
    assert response.status_code == 422
    errors = {}
    for item in response.json()["detail"]:
        errors.setdefault(item["loc"][-1], []).append(item["msg"])
    return errors


def labels(client, **filters):
    return [entry["label"] for entry in client.get(ENTRIES, filters).json()["items"]]


# Access


@pytest.mark.parametrize(("method", "path"), OPERATIONS)
def test_the_treasury_is_reserved_to_signed_in_members(client, method, path):
    """
    Given a visitor without an access token
    When they read or write the journal or the results
    Then the API refuses with a 401
    """
    response = getattr(client, method)(path)

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentification requise."}


@pytest.mark.parametrize(("method", "path"), OPERATIONS)
def test_the_treasury_is_refused_to_accounts_outside_the_board(method, path):
    """
    Given an active account outside the board
    When it reads or writes the journal or the results
    Then the API refuses with a 403
    """
    response = getattr(client_of(UserFactory()), method)(path)

    assert response.status_code == 403
    assert response.json() == {"detail": "Accès réservé aux membres du bureau."}


# Recording


def test_a_member_records_an_expense_of_an_event(board_client, board_member):
    """
    Given the brocante
    When a member records the drinks bought for its bar, by the journal's form
    Then the entry is created, as they recorded it, and counts for the brocante
    """
    brocante = EventFactory(title="Brocante")

    response = board_client.post(
        ENTRIES, form(event=brocante.id, supplier="Supermarché", note="Pour la buvette")
    )

    assert response.status_code == 201
    entry = LedgerEntry.objects.get()
    assert response.json() == {
        "id": entry.id,
        "date": "2026-09-12",
        "kind": "expense",
        "label": "Courses buvette",
        "amount": "286.30",
        "category": "drinks",
        "payment_method": "association_card",
        "advanced_by": None,
        "reimbursed_on": None,
        "reimbursement_method": None,
        "event": {"id": brocante.id, "title": "Brocante", "starts_at": iso(brocante.starts_at)},
        "supplier": "Supermarché",
        "note": "Pour la buvette",
        "created_by": member_json(board_member),
        "created_at": iso(entry.created_at),
        "receipt": None,
        "receipt_state": "missing",
        "contact": member_json(board_member),
    }


def test_an_entry_without_an_event_is_of_the_general_running(board_client):
    """
    Given the subsidy of the municipality, which no event takes
    When a member records it without an event, a supplier or a note
    Then the entry has none of them
    """
    response = board_client.post(
        ENTRIES,
        form(kind="income", label="Subvention municipale", category="grant", amount="1500"),
    )

    assert response.status_code == 201
    assert (response.json()["event"], response.json()["supplier"], response.json()["note"]) == (
        None,
        "",
        "",
    )
    assert response.json()["amount"] == "1500.00"


def test_an_advance_names_the_member_who_paid_it(board_client):
    """
    Given Marc, a board member, who paid the drinks with his own money
    When a member records the expense as advanced by him
    Then the entry names him
    """
    marc = BoardMemberFactory(first_name="Marc", last_name="Durand")

    response = board_client.post(ENTRIES, form(payment_method="advance", advanced_by=marc.id))

    assert response.status_code == 201
    assert response.json()["advanced_by"] == member_json(marc)


@pytest.mark.parametrize(
    ("changes", "errors"),
    [
        ({"label": "   "}, {"label": ["Ce champ ne peut pas être vide."]}),
        ({"amount": "0"}, {"amount": ["Indiquez un montant supérieur à zéro."]}),
        (
            {"amount": "12.345"},
            {"amount": ["Assurez-vous qu’il n’y a pas plus de 2 chiffres après la virgule."]},
        ),
        ({"amount": "douze"}, {"amount": ["Saisissez un nombre."]}),
        ({"category": "bar"}, {"category": ["Choisissez une catégorie de dépense."]}),
        ({"event": "999999"}, {"event": ["Choisissez un événement existant."]}),
        (
            {"payment_method": "advance"},
            {"advanced_by": ["Choisissez le membre qui a avancé la dépense."]},
        ),
        (
            {"kind": "income", "category": "bar", "payment_method": "advance"},
            {
                "payment_method": ["Une recette n’est pas avancée par un membre."],
                "advanced_by": ["Choisissez le membre qui a avancé la dépense."],
            },
        ),
    ],
)
def test_a_faulty_entry_is_refused_in_french_under_its_fields(board_client, changes, errors):
    """
    Given an entry without a label, of nothing, of a third of a cent, of no
    number, of the wrong category, of an unknown event, or an advance without
    its member, or an income advanced
    When a member records it
    Then it is refused with a 422, each error under its field, and nothing is
    written
    """
    response = board_client.post(ENTRIES, form(**changes))

    assert field_errors(response) == errors
    assert not LedgerEntry.objects.exists()


def test_an_entry_dated_in_the_future_is_refused(board_client):
    """
    Given tomorrow's date
    When a member records an entry on it
    Then its date is refused
    """
    tomorrow = ahead(1)

    response = board_client.post(ENTRIES, form(date=tomorrow.isoformat()))

    assert field_errors(response) == {"date": ["La date ne peut pas être dans le futur."]}


def test_an_advance_names_a_board_member_only(board_client):
    """
    Given an account outside the board
    When a member records an advance as paid by it
    Then the member is refused
    """
    outsider = UserFactory()

    response = board_client.post(ENTRIES, form(payment_method="advance", advanced_by=outsider.id))

    assert field_errors(response) == {"advanced_by": ["Choisissez un membre du bureau."]}


def test_a_member_named_outside_an_advance_is_refused(board_client):
    """
    Given an expense paid with the association's card
    When a member records it naming Marc as the one who paid
    Then the member is refused under its field
    """
    marc = BoardMemberFactory()

    response = board_client.post(ENTRIES, form(advanced_by=marc.id))

    assert field_errors(response) == {
        "advanced_by": ["Seule une avance nomme le membre qui l’a faite."]
    }


def test_a_form_field_missing_is_told_under_its_field(board_client):
    """
    Given the journal's form without its kind
    When a member sends it
    Then the kind is told missing, under its field of the form
    """
    response = board_client.post(ENTRIES, form(kind=None))

    assert response.status_code == 422
    assert response.json()["detail"] == [
        {"type": "missing", "loc": ["form", "kind"], "msg": "Ce champ est obligatoire."}
    ]


# Reading


def test_a_member_reads_an_entry(board_client):
    """
    Given an advance of Sophie for the goûter
    When a member reads it
    Then they get it, with whoever advanced and recorded it
    """
    sophie = BoardMemberFactory(first_name="Sophie", last_name="Lambert")
    entry = AdvanceFactory(label="Courses goûter", advanced_by=sophie, created_by=sophie)

    response = board_client.get(entry_url(entry.pk))

    assert response.status_code == 200
    assert response.json()["label"] == "Courses goûter"
    assert response.json()["advanced_by"] == member_json(sophie)
    assert response.json()["created_by"] == member_json(sophie)


@pytest.mark.parametrize("method", ["get", "put", "delete"])
def test_an_unknown_entry_is_not_found(board_client, method):
    """
    Given no entry of that id
    When a member reads, corrects or deletes it
    Then the API answers 404, in French
    """
    # A correction whole: its body is checked before the entry is looked up.
    body = whole(LedgerEntryFactory.build()) if method == "put" else {}

    response = send(board_client, method, entry_url(999999), body)

    assert response.status_code == 404
    assert response.json() == {"detail": "Introuvable."}


def test_an_entry_id_that_is_no_number_is_refused(board_client):
    """
    Given an address naming an entry by a word
    When a member reads it
    Then it is refused with a 422, as the operation declares
    """
    response = board_client.get(entry_url("courses"))

    assert response.status_code == 422


# Listing


def test_the_journal_comes_the_latest_entry_first(board_client):
    """
    Given three entries, two of them on the same day
    When a member lists the journal
    Then the latest date comes first, and on a day the latest recorded first
    """
    LedgerEntryFactory(label="Assurance", date=dt.date(2026, 9, 5))
    LedgerEntryFactory(label="Courses", date=dt.date(2026, 9, 12))
    LedgerEntryFactory(label="Location", date=dt.date(2026, 9, 12))

    assert labels(board_client) == ["Location", "Courses", "Assurance"]


def test_the_journal_keeps_the_entries_of_a_fiscal_year(board_client):
    """
    Given entries on the last day of 2025 and the first of 2026
    When a member lists the journal of 2026, then of 2025
    Then each year keeps its own entry
    """
    LedgerEntryFactory(label="Réveillon", date=dt.date(2025, 12, 31))
    LedgerEntryFactory(label="Galette", date=dt.date(2026, 1, 1))

    assert labels(board_client, year=2026) == ["Galette"]
    assert labels(board_client, year=2025) == ["Réveillon"]


def test_the_journal_keeps_the_entries_of_an_event_or_of_the_general_running(board_client):
    """
    Given an entry of the brocante, one of Halloween, and one without an event
    When a member lists the brocante's entries, then those of the general running
    Then each list keeps its own
    """
    brocante = EventFactory()
    LedgerEntryFactory(label="Buvette", event=brocante)
    LedgerEntryFactory(label="Goûter", event=EventFactory())
    IncomeFactory(label="Cotisations")

    assert labels(board_client, event=brocante.id) == ["Buvette"]
    assert labels(board_client, general="true") == ["Cotisations"]
    assert sorted(labels(board_client, general="false")) == ["Buvette", "Cotisations", "Goûter"]


def test_the_journal_comes_by_page(board_client):
    """
    Given three entries
    When a member lists them two by two
    Then the first page holds two, and tells there are three
    """
    LedgerEntryFactory.create_batch(3)

    response = board_client.get(ENTRIES, {"page_size": 2})

    assert response.json()["count"] == 3
    assert len(response.json()["items"]) == 2


def test_listing_the_journal_reads_its_events_and_people_at_once(
    board_client, django_assert_max_num_queries
):
    """
    Given five advances, each of an event, a member and its author
    When a member lists the journal
    Then the entries, their events and their people take a fixed number of
    queries
    """
    AdvanceFactory.create_batch(5, event=EventFactory(), created_by=BoardMemberFactory())

    # Authentication (2), count and page of entries with their links.
    with django_assert_max_num_queries(4):
        response = board_client.get(ENTRIES)

    assert len(response.json()["items"]) == 5


@pytest.mark.parametrize(
    ("year", "message"),
    [
        ("0", "Assurez-vous que cette valeur est supérieure ou égale à 1."),
        ("10000", "Assurez-vous que cette valeur est inférieure ou égale à 9999."),
    ],
)
def test_a_year_the_dates_cannot_hold_is_refused(board_client, year, message):
    """
    Given a year before the first or after the last a date can hold
    When a member lists its journal
    Then it is refused with a 422, in French
    """
    response = board_client.get(ENTRIES, {"year": year})

    assert field_errors(response) == {"year": [message]}


# Correcting


def test_a_member_corrects_an_entry_whole(board_client):
    """
    Given an expense of 12,50 € recorded by Camille
    When another member corrects its label and amount
    Then it holds the correction, still recorded by Camille
    """
    author = BoardMemberFactory()
    entry = LedgerEntryFactory(created_by=author)

    response = correct(board_client, entry, label="Courses goûter", amount="47.85")

    assert response.status_code == 200
    assert (response.json()["label"], response.json()["amount"]) == ("Courses goûter", "47.85")
    assert response.json()["created_by"] == member_json(author)


def test_a_former_member_stays_the_one_who_advanced_until_it_changes(board_client):
    """
    Given an advance of Marc, who has since left the board
    When a member corrects its label, then names Marc again on a new advance
    Then the correction keeps Marc, but a new advance cannot name him
    """
    marc = BoardMemberFactory()
    entry = AdvanceFactory(advanced_by=marc)
    marc.is_active = False
    marc.save()

    kept = correct(board_client, entry, label="Courses buvette de la brocante")
    named = board_client.post(ENTRIES, form(payment_method="advance", advanced_by=marc.id))

    assert kept.status_code == 200
    assert kept.json()["advanced_by"]["id"] == marc.id
    assert field_errors(named) == {"advanced_by": ["Choisissez un membre du bureau."]}


def test_an_advance_changed_to_another_method_drops_its_member(board_client):
    """
    Given an advance of a member who has since left the board
    When a member corrects it to the association's card, the member still sent
    Then the member is refused under its field, not by the database
    """
    marc = BoardMemberFactory()
    entry = AdvanceFactory(advanced_by=marc)
    marc.is_active = False
    marc.save()

    response = correct(board_client, entry, payment_method="association_card")

    assert field_errors(response) == {
        "advanced_by": [
            "Choisissez un membre du bureau.",
            "Seule une avance nomme le membre qui l’a faite.",
        ]
    }


def test_an_advance_whose_account_was_deleted_keeps_no_member(board_client):
    """
    Given an advance whose member's account was deleted
    When a member corrects its label, then names another member
    Then the first correction keeps it without a member, the second names them
    """
    entry = AdvanceFactory()
    entry.advanced_by.delete()
    entry.refresh_from_db()
    sophie = BoardMemberFactory()

    kept = correct(board_client, entry, label="Courses")
    named = correct(board_client, entry, label="Courses", advanced_by=sophie.id)

    assert (kept.status_code, kept.json()["advanced_by"]) == (200, None)
    assert named.json()["advanced_by"]["id"] == sophie.id


def test_a_reimbursed_advance_stays_an_advance(board_client):
    """
    Given an advance reimbursed by transfer
    When a member corrects it to the association's card
    Then the payment method is refused: its reimbursement is to be cancelled first
    """
    entry = AdvanceFactory(
        reimbursed_on=dt.date(2026, 9, 20), reimbursement_method=ReimbursementMethod.TRANSFER
    )

    response = correct(board_client, entry, payment_method="association_card", advanced_by=None)

    assert field_errors(response) == {
        "payment_method": [
            "Une avance remboursée reste une avance : annulez d’abord son remboursement."
        ]
    }


def test_a_correction_keeps_the_reimbursement_of_an_advance(board_client):
    """
    Given an advance reimbursed by transfer
    When a member corrects its label
    Then it stays reimbursed
    """
    entry = AdvanceFactory(
        reimbursed_on=dt.date(2026, 9, 20), reimbursement_method=ReimbursementMethod.TRANSFER
    )

    response = correct(board_client, entry, label="Courses")

    assert (response.json()["reimbursed_on"], response.json()["reimbursement_method"]) == (
        "2026-09-20",
        "transfer",
    )


# Deleting


def test_a_member_deletes_an_entry_and_its_receipt_stays(board_client):
    """
    Given an expense proved by an invoice
    When a member deletes the expense
    Then the entry is gone, and the invoice stays among the documents
    """
    invoice = DocumentFactory()
    entry = LedgerEntryFactory(receipt=invoice)

    response = board_client.delete(entry_url(entry.pk))

    assert response.status_code == 204
    assert not LedgerEntry.objects.exists()
    invoice.refresh_from_db()
