import datetime as dt
from decimal import Decimal

import pytest
from django.db import IntegrityError

from tests.accounts.factories import BoardMemberFactory
from tests.documents.factories import DocumentFactory
from tests.helpers import ahead, errors_of
from tests.treasury.factories import AdvanceFactory, IncomeFactory, LedgerEntryFactory
from treasury.models import (
    LedgerCategory,
    LedgerEntry,
    LedgerEntryKind,
    LedgerPaymentMethod,
    ReimbursementMethod,
)

pytestmark = pytest.mark.django_db


def test_an_entry_reads_as_its_label():
    """
    Given an entry « Courses buvette »
    When it is shown in a shell or a log
    Then it reads as its label
    """
    assert str(LedgerEntryFactory.build(label="Courses buvette")) == "Courses buvette"


@pytest.mark.parametrize("amount", [Decimal("0.00"), Decimal("-12.50")])
def test_an_amount_is_more_than_zero(amount):
    """
    Given an entry of nothing, or of a negative sum
    When it is checked, then written
    Then its amount is refused, and the database refuses it too
    """
    entry = LedgerEntryFactory.build(amount=amount)

    assert errors_of(entry) == {"amount": ["Indiquez un montant supérieur à zéro."]}
    with pytest.raises(IntegrityError):
        entry.save()


@pytest.mark.parametrize(
    ("kind", "category", "message"),
    [
        (LedgerEntryKind.EXPENSE, LedgerCategory.BAR, "Choisissez une catégorie de dépense."),
        (LedgerEntryKind.INCOME, LedgerCategory.FOOD, "Choisissez une catégorie de recette."),
    ],
)
def test_a_category_belongs_to_its_kind(kind, category, message):
    """
    Given an expense of the bar, or an income of food
    When it is checked, then written
    Then its category is refused under its field, and the database refuses it
    """
    entry = LedgerEntryFactory.build(
        kind=kind,
        category=category,
        payment_method=LedgerPaymentMethod.CASH,
    )

    assert errors_of(entry) == {"category": [message]}
    with pytest.raises(IntegrityError):
        entry.save()


@pytest.mark.parametrize("kind", [LedgerEntryKind.EXPENSE, LedgerEntryKind.INCOME])
def test_misc_belongs_to_both_kinds(kind):
    """
    Given an expense, or an income, of « Divers »
    When it is checked
    Then it passes
    """
    LedgerEntryFactory.build(
        kind=kind,
        category=LedgerCategory.MISC,
        payment_method=LedgerPaymentMethod.CASH,
    ).full_clean()


def test_an_income_is_never_advanced():
    """
    Given an income « advanced » by a member
    When it is checked, then written
    Then its payment method is refused, and the database refuses it
    """
    entry = IncomeFactory.build(
        payment_method=LedgerPaymentMethod.ADVANCE,
        advanced_by=BoardMemberFactory(),
    )

    assert errors_of(entry) == {"payment_method": ["Une recette n’est pas avancée par un membre."]}
    with pytest.raises(IntegrityError):
        entry.save()


def test_only_an_advance_names_a_member():
    """
    Given an expense paid with the association's card, naming a member
    When it is checked, then written
    Then the member is refused under its field, and the database refuses it
    """
    entry = LedgerEntryFactory.build(advanced_by=BoardMemberFactory())

    assert errors_of(entry) == {"advanced_by": ["Seule une avance nomme le membre qui l’a faite."]}
    with pytest.raises(IntegrityError):
        entry.save()


def test_an_advance_without_its_member_is_left_to_the_service():
    """
    Given an advance that names no member, as one whose account was deleted
    When it is checked and written
    Then the model and the database let it through: the service decides
    """
    entry = AdvanceFactory.build(advanced_by=None)

    entry.full_clean()
    entry.save()


def test_only_an_advance_is_reimbursed():
    """
    Given an expense paid with the association's card, marked reimbursed
    When it is checked, then written
    Then the payment method says to cancel the reimbursement first, and the
    database refuses it
    """
    entry = LedgerEntryFactory.build(
        reimbursed_on=dt.date(2026, 9, 20),
        reimbursement_method=ReimbursementMethod.TRANSFER,
    )

    assert errors_of(entry) == {
        "payment_method": [
            "Une avance remboursée reste une avance : annulez d’abord son remboursement."
        ]
    }
    with pytest.raises(IntegrityError):
        entry.save()


@pytest.mark.parametrize(
    "fields",
    [
        {"reimbursed_on": dt.date(2026, 9, 20)},
        {"reimbursement_method": ReimbursementMethod.CASH},
    ],
)
def test_the_database_keeps_a_reimbursement_dated_and_paid_by_a_method(fields):
    """
    Given an advance with the date of its reimbursement but not its method, or
    the other way round
    When it is written
    Then the database refuses it
    """
    with pytest.raises(IntegrityError):
        AdvanceFactory(**fields)


def test_a_reimbursement_never_comes_before_its_advance():
    """
    Given an advance of 15 September, reimbursed on 14 September
    When it is checked, then written
    Then the date of the reimbursement is refused, and the database refuses it
    """
    entry = AdvanceFactory()
    entry.reimbursed_on = dt.date(2026, 9, 14)
    entry.reimbursement_method = ReimbursementMethod.CASH

    assert errors_of(entry) == {
        "reimbursed_on": ["Le remboursement ne peut pas précéder l’avance."]
    }
    with pytest.raises(IntegrityError):
        entry.save()


def test_dates_are_never_in_the_future():
    """
    Given an advance dated tomorrow, reimbursed tomorrow
    When it is checked
    Then both dates are refused
    """
    tomorrow = ahead(1)
    entry = AdvanceFactory.build(
        date=tomorrow,
        reimbursed_on=tomorrow,
        reimbursement_method=ReimbursementMethod.CASH,
        advanced_by=BoardMemberFactory(),
    )

    assert errors_of(entry) == {
        "date": ["La date ne peut pas être dans le futur."],
        "reimbursed_on": ["La date ne peut pas être dans le futur."],
    }


def test_a_deleted_account_leaves_its_advances_and_entries_behind():
    """
    Given an advance of a member, which they recorded themselves
    When their account is deleted
    Then the advance stays, without anyone named
    """
    member = BoardMemberFactory()
    entry = AdvanceFactory(advanced_by=member, created_by=member)

    member.delete()

    entry.refresh_from_db()
    assert (entry.advanced_by, entry.created_by) == (None, None)


def test_a_document_proves_a_single_entry_and_its_deletion_leaves_the_entry():
    """
    Given an entry proved by an invoice
    When another entry takes the same invoice, then the invoice is deleted
    Then the second is refused under its receipt, and the first stays without one
    """
    invoice = DocumentFactory()
    entry = LedgerEntryFactory(receipt=invoice)

    assert errors_of(LedgerEntryFactory.build(receipt=invoice)) == {
        "receipt": ["Ce document justifie déjà une autre ligne."]
    }
    invoice.delete()
    entry.refresh_from_db()
    assert entry.receipt is None
    assert LedgerEntry.objects.count() == 1
