"""The advances of the members, until the committee pays them back (6.5, A18)."""

import datetime as dt
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from tests.accounts.factories import BoardMemberFactory
from tests.treasury.factories import AdvanceFactory, LedgerEntryFactory
from treasury.models import LedgerEntry, ReimbursementMethod

pytestmark = pytest.mark.django_db

ENTRIES = "/api/board/treasury/entries"


def url(entry_id):
    return f"{ENTRIES}/{entry_id}/reimbursement"


def reimburse(client, entry, **changes):
    payload = {"reimbursed_on": "2026-09-20", "reimbursement_method": "transfer"} | changes
    return client.post(url(entry.pk), payload, content_type="application/json")


def messages(response):
    assert response.status_code == 422
    return {tuple(item["loc"]): item["msg"] for item in response.json()["detail"]}


def reimbursed(**fields):
    return AdvanceFactory(
        reimbursed_on=dt.date(2026, 9, 20), reimbursement_method=ReimbursementMethod.CASH, **fields
    )


def test_a_member_marks_an_advance_reimbursed(board_client):
    """
    Given Marc's advance of 286,30 €, on 12 September
    When a member marks it reimbursed by transfer on 20 September
    Then the advance holds its reimbursement, and no second expense is written
    """
    entry = AdvanceFactory(date=dt.date(2026, 9, 12), amount=Decimal("286.30"))

    response = reimburse(board_client, entry)

    assert response.status_code == 200
    assert (response.json()["reimbursed_on"], response.json()["reimbursement_method"]) == (
        "2026-09-20",
        "transfer",
    )
    assert LedgerEntry.objects.count() == 1


def test_an_advance_of_a_member_who_left_is_reimbursed_all_the_same(board_client):
    marc = BoardMemberFactory()
    entry = AdvanceFactory(advanced_by=marc)
    marc.is_active = False
    marc.save()

    response = reimburse(board_client, entry)

    assert response.status_code == 200
    assert response.json()["advanced_by"]["id"] == marc.id


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        (lambda: LedgerEntryFactory(), "Seule une avance se rembourse."),
        (reimbursed, "Cette avance est déjà remboursée."),
    ],
)
def test_only_an_advance_owed_is_reimbursed(board_client, entry, message):
    response = reimburse(board_client, entry())

    assert messages(response) == {("body",): message}


@pytest.mark.parametrize(
    ("changes", "errors"),
    [
        (
            {"reimbursed_on": "2999-01-01"},
            {("body", "reimbursed_on"): "La date ne peut pas être dans le futur."},
        ),
        (
            {"reimbursed_on": "2026-09-14"},
            {("body", "reimbursed_on"): "Le remboursement ne peut pas précéder l’avance."},
        ),
    ],
)
def test_a_reimbursement_is_dated_after_its_advance_and_never_ahead(board_client, changes, errors):
    """
    Given an advance of 15 September
    When a member marks it reimbursed in the future, or on 14 September
    Then the date is refused under its field, and the advance stays owed
    """
    entry = AdvanceFactory(date=dt.date(2026, 9, 15))

    response = reimburse(board_client, entry, **changes)

    assert messages(response) == errors
    entry.refresh_from_db()
    assert entry.reimbursed_on is None


def test_a_reimbursement_needs_a_method_of_its_own(board_client):
    response = reimburse(board_client, AdvanceFactory(), reimbursement_method="advance")

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "payload", "reimbursement_method"]


def test_marking_an_advance_reimbursed_locks_it(board_client):
    entry = AdvanceFactory()

    with CaptureQueriesContext(connection) as queries:
        reimburse(board_client, entry)

    locks = [query["sql"] for query in queries.captured_queries if "FOR UPDATE" in query["sql"]]
    assert len(locks) == 1
    assert LedgerEntry._meta.db_table in locks[0]


def test_a_reimbursement_marked_by_mistake_is_cancelled(board_client):
    """
    Given an advance marked reimbursed by mistake
    When a member cancels its reimbursement
    Then the advance is owed again
    """
    entry = reimbursed()

    response = board_client.delete(url(entry.pk))

    assert response.status_code == 200
    assert (response.json()["reimbursed_on"], response.json()["reimbursement_method"]) == (
        None,
        None,
    )


def test_an_advance_owed_has_no_reimbursement_to_cancel(board_client):
    response = board_client.delete(url(AdvanceFactory().pk))

    assert messages(response) == {("body",): "Cette avance n’est pas remboursée."}


@pytest.mark.parametrize("method", ["post", "delete"])
def test_the_reimbursement_of_an_unknown_entry_is_not_found(board_client, method):
    body = {"reimbursed_on": "2026-09-20", "reimbursement_method": "cash"}

    response = getattr(board_client, method)(url(999999), body, content_type="application/json")

    assert response.status_code == 404


def test_the_journal_keeps_every_year_s_advances_owed(board_client):
    """
    Given advances owed of 2025 and 2026, an advance reimbursed and an expense
    paid with the card
    When a member lists the advances to reimburse
    Then the two advances owed come, whatever their year
    """
    AdvanceFactory(label="Réveillon", date=dt.date(2025, 12, 31))
    AdvanceFactory(label="Galette", date=dt.date(2026, 1, 1))
    reimbursed(label="Remboursée")
    LedgerEntryFactory(label="Carte")

    entries = board_client.get(ENTRIES, {"to_reimburse": "true"}).json()["items"]

    assert {entry["label"] for entry in entries} == {"Réveillon", "Galette"}
