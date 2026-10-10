import datetime as dt
from decimal import Decimal

import factory
from django.utils import timezone

from equipment.models import Equipment, EquipmentCategory, Loan, LoanBorrowerType, LoanLine
from tests.events.factories import EventFactory


class EquipmentFactory(factory.django.DjangoModelFactory):
    """Four marquees, none under repair."""

    class Meta:
        model = Equipment

    name = factory.Sequence(lambda n: f"Barnums 3 × 3 m ({n})")
    category = EquipmentCategory.MARQUEES
    storage_location = "Garage communal"
    total_quantity = 4
    unit_value = Decimal("250.00")


class LoanFactory(factory.django.DjangoModelFactory):
    """A loan to an association, confirmed, a fortnight ahead, for three days.

    Its number belongs to a year no service numbers a loan in: it never meets
    the numbers a test has the service give.
    """

    class Meta:
        model = Loan

    number = factory.Sequence(lambda n: f"P-1990-{n:03}")
    borrower_type = LoanBorrowerType.ASSOCIATION
    borrower_name = "Club de football"
    purpose = "Tournoi jeunes"
    start_date = factory.LazyFunction(lambda: timezone.localdate() + dt.timedelta(days=15))
    end_date = factory.LazyAttribute(lambda loan: loan.start_date + dt.timedelta(days=2))
    deposit_amount = Decimal("150.00")


class CommitteeLoanFactory(LoanFactory):
    """The equipment the committee keeps for one of its events."""

    number = None
    borrower_type = LoanBorrowerType.COMMITTEE
    borrower_name = ""
    purpose = ""
    deposit_amount = Decimal(0)
    event = factory.SubFactory(EventFactory)


class LoanLineFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = LoanLine

    loan = factory.SubFactory(LoanFactory)
    equipment = factory.SubFactory(EquipmentFactory)
    quantity = 1


def lend(equipment, quantity, start, end, **fields):
    """A loan of a quantity of one equipment, both days counted."""
    loan = (CommitteeLoanFactory if "event" in fields else LoanFactory)(
        start_date=start, end_date=end, **fields
    )
    LoanLineFactory(loan=loan, equipment=equipment, quantity=quantity)
    return loan
