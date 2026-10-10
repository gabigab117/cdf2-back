import datetime as dt
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models import ProtectedError
from django.utils import timezone

from equipment.models import (
    Equipment,
    EquipmentCategory,
    Loan,
    LoanLine,
    LoanNumberSequence,
    LoanStatus,
)
from tests.equipment.factories import (
    CommitteeLoanFactory,
    EquipmentFactory,
    LoanFactory,
    LoanLineFactory,
)
from tests.events.factories import EventFactory

pytestmark = pytest.mark.django_db

START = dt.date(2026, 10, 16)


def errors_of(instance):
    with pytest.raises(ValidationError) as error:
        instance.full_clean()
    return error.value.message_dict


def test_equipment_loans_and_lines_read_as_what_they_are():
    """
    Given marquees, a loan of two of them, and the equipment kept for an event
    When they are shown in a shell or a log
    Then each reads as its name, its number, or its event, and a line as its
    equipment and pieces
    """
    marquees = EquipmentFactory(name="Barnums 3 × 3 m")
    loan = LoanFactory(number="P-2026-018")
    kept = CommitteeLoanFactory(event=EventFactory(title="Halloween des enfants"))
    line = LoanLineFactory(loan=loan, equipment=marquees, quantity=2)

    assert str(marquees) == "Barnums 3 × 3 m"
    assert (str(loan), str(kept)) == ("P-2026-018", "Halloween des enfants")
    assert (loan.display_name, kept.display_name) == ("Club de football", "Halloween des enfants")
    assert str(line) == "Barnums 3 × 3 m : 2"
    assert str(LoanNumberSequence(year=2026, last_number=18)) == "2026 : 18"


# Equipment


def test_two_equipment_never_share_a_name_whatever_its_case():
    """
    Given marquees named « Barnums 3 × 3 m »
    When other equipment is named « barnums 3 × 3 M »
    Then it is refused, on the form
    """
    EquipmentFactory(name="Barnums 3 × 3 m")
    duplicate = Equipment(
        name="barnums 3 × 3 M", category=EquipmentCategory.MARQUEES, total_quantity=2
    )

    assert errors_of(duplicate) == {"__all__": ["Un matériel porte déjà ce nom."]}


def test_pieces_under_repair_never_outnumber_the_equipment():
    """
    Given two benches
    When three are said to be under repair
    Then it is refused under the quantity under repair, and by the database
    """
    benches = Equipment(
        name="Bancs pliants",
        category=EquipmentCategory.FURNITURE,
        total_quantity=2,
        repair_quantity=3,
    )

    assert errors_of(benches) == {
        "repair_quantity": ["La quantité en réparation dépasse la quantité totale."]
    }
    with pytest.raises(IntegrityError):
        benches.save()


def test_a_quantity_left_out_is_its_own_fields_error():
    """
    Given equipment without its quantity
    When it is checked
    Then the quantity alone is reported, as required
    """
    benches = Equipment(name="Bancs pliants", category=EquipmentCategory.FURNITURE)

    assert errors_of(benches) == {
        "total_quantity": ["Ce champ ne peut pas contenir la valeur nulle."]
    }


def test_lent_equipment_cannot_be_deleted_but_a_loan_takes_its_lines_along():
    """
    Given marquees lent once
    When the marquees are deleted
    Then it is refused: the loan keeps them in its history
    But deleting the loan takes its lines along, and frees the marquees
    """
    line = LoanLineFactory()

    with pytest.raises(ProtectedError):
        line.equipment.delete()

    line.loan.delete()
    line.equipment.delete()

    assert not LoanLine.objects.exists()
    assert not Equipment.objects.exists()


# Loans


def test_a_committee_loan_needs_its_event_and_a_loan_to_someone_its_borrower():
    """
    Given the equipment kept for no event, and a loan to nobody
    When they are checked
    Then each is refused under the field it lacks
    """
    assert errors_of(CommitteeLoanFactory.build(event=None)) == {
        "event": ["Choisissez l’événement du comité."]
    }
    assert errors_of(LoanFactory.build(borrower_name="")) == {
        "borrower_name": ["Ce champ ne peut pas être vide."]
    }


@pytest.mark.parametrize(
    ("end", "message"),
    [
        (START - dt.timedelta(days=1), "La date de retour est avant la date de sortie."),
        (START + dt.timedelta(days=31), "Un prêt dure au plus 31 jours."),
    ],
)
def test_a_loan_ends_after_it_starts_and_lasts_a_month_at_most(end, message):
    """
    Given a loan that ends before it starts, or lasts 32 days
    When it is checked
    Then it is refused under its return date
    """
    loan = LoanFactory.build(start_date=START, end_date=end)

    assert errors_of(loan) == {"end_date": [message]}


def test_a_loan_of_a_day_or_of_31_days_is_accepted():
    """
    Given a loan of a single day, and one of 31 days, both counted
    When they are checked
    Then both pass
    """
    LoanFactory.build(start_date=START, end_date=START).full_clean()
    LoanFactory.build(start_date=START, end_date=START + dt.timedelta(days=30)).full_clean()


def test_a_date_left_out_is_its_own_fields_error():
    """
    Given a loan without its return date
    When it is checked
    Then the date alone is reported, as required
    """
    assert errors_of(LoanFactory.build(end_date=None)) == {
        "end_date": ["Ce champ ne peut pas contenir la valeur nulle."]
    }


def test_an_event_keeps_a_single_reservation_unless_it_was_cancelled():
    """
    Given an event whose first reservation was cancelled, and a second one
    When a third reservation is checked for it
    Then it is refused under the event, while the second checks fine
    """
    event = EventFactory()
    CommitteeLoanFactory(event=event, status=LoanStatus.CANCELLED)
    kept = CommitteeLoanFactory(event=event)

    assert errors_of(CommitteeLoanFactory.build(event=event)) == {
        "event": ["Cet événement a déjà sa réservation de matériel."]
    }
    kept.full_clean()


def test_deleting_an_event_deletes_its_reservation():
    """
    Given the equipment kept for an event
    When the event is deleted
    Then its reservation and its lines go along
    """
    line = LoanLineFactory(loan=CommitteeLoanFactory())

    line.loan.event.delete()

    assert not Loan.objects.exists()
    assert not LoanLine.objects.exists()


@pytest.mark.parametrize(
    "fields",
    [
        {"number": "P-2026-001"},
        {"phone": "01 23 45 67 89"},
        {"deposit_amount": Decimal("150.00")},
        {"borrower_name": "Club de football"},
    ],
)
def test_the_database_keeps_a_committee_loan_internal(fields):
    """
    Given the equipment kept for an event
    When it is written with a number, a phone, a deposit or a borrower
    Then the database refuses it
    """
    with pytest.raises(IntegrityError):
        CommitteeLoanFactory(**fields)


@pytest.mark.parametrize("fields", [{"number": None}, {"borrower_name": ""}])
def test_the_database_keeps_a_loan_to_someone_numbered_and_named(fields):
    """
    Given a loan to someone
    When it is written without a number or a borrower
    Then the database refuses it
    """
    with pytest.raises(IntegrityError):
        LoanFactory(**fields)


def test_the_database_keeps_events_to_the_committee():
    """
    Given a loan to someone
    When it is written for an event
    Then the database refuses it: only the committee keeps equipment for one
    """
    with pytest.raises(IntegrityError):
        LoanFactory(event=EventFactory())


@pytest.mark.parametrize(
    ("status", "dated"), [(LoanStatus.RETURNED, False), (LoanStatus.OUT, True)]
)
def test_the_database_dates_a_loan_returned_and_none_other(status, dated):
    """
    Given a loan returned without the date of its return, or one out with one
    When it is written
    Then the database refuses it
    """
    with pytest.raises(IntegrityError):
        LoanFactory(status=status, returned_at=timezone.now() if dated else None)


def test_the_database_refuses_a_loan_ending_before_it_starts():
    """
    Given a loan whose return comes before its start
    When it is written
    Then the database refuses it
    """
    with pytest.raises(IntegrityError):
        LoanFactory(start_date=START, end_date=START - dt.timedelta(days=1))


# Lines


def test_a_line_takes_some_pieces_and_its_return_stays_within_them():
    """
    Given a line of no piece, and a line of two returned with three damaged or missing
    When they are checked
    Then the first is refused under its quantity, the second on the form
    """
    loan, marquees = LoanFactory(), EquipmentFactory()

    assert errors_of(LoanLine(loan=loan, equipment=marquees, quantity=0)) == {
        "quantity": ["Assurez-vous que cette valeur est supérieure ou égale à 1."]
    }
    returned = LoanLine(
        loan=loan, equipment=marquees, quantity=2, damaged_quantity=2, missing_quantity=1
    )
    assert errors_of(returned) == {
        "__all__": ["Les pièces abîmées et manquantes dépassent la quantité prêtée."]
    }


def test_an_equipment_appears_once_in_a_loan():
    """
    Given a loan of marquees
    When a second line of the same marquees is checked
    Then it is refused
    """
    line = LoanLineFactory()

    duplicate = LoanLine(loan=line.loan, equipment=line.equipment, quantity=1)

    assert errors_of(duplicate) == {"__all__": ["Ce matériel figure déjà dans le prêt."]}


@pytest.mark.parametrize(
    "fields",
    [{"quantity": 0}, {"quantity": 2, "damaged_quantity": 2, "missing_quantity": 1}],
)
def test_the_database_keeps_the_pieces_of_a_line_within_reason(fields):
    """
    Given a line of no piece, or one returned with more pieces than it lent
    When it is written
    Then the database refuses it
    """
    with pytest.raises(IntegrityError):
        LoanLineFactory(**fields)
