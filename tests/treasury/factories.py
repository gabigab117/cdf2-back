import datetime as dt
from decimal import Decimal

import factory

from tests.accounts.factories import BoardMemberFactory
from treasury.models import LedgerCategory, LedgerEntry, LedgerEntryKind, LedgerPaymentMethod


class LedgerEntryFactory(factory.django.DjangoModelFactory):
    """An expense of food, paid with the association's card in mid-September 2026."""

    class Meta:
        model = LedgerEntry

    date = dt.date(2026, 9, 15)
    kind = LedgerEntryKind.EXPENSE
    label = factory.Sequence(lambda n: f"Courses buvette ({n})")
    amount = Decimal("12.50")
    category = LedgerCategory.FOOD
    payment_method = LedgerPaymentMethod.ASSOCIATION_CARD


class IncomeFactory(LedgerEntryFactory):
    """Takings of the bar, in cash."""

    kind = LedgerEntryKind.INCOME
    label = factory.Sequence(lambda n: f"Recette buvette ({n})")
    category = LedgerCategory.BAR
    payment_method = LedgerPaymentMethod.CASH


class AdvanceFactory(LedgerEntryFactory):
    """An expense a board member paid with their own money, not paid back yet."""

    payment_method = LedgerPaymentMethod.ADVANCE
    advanced_by = factory.SubFactory(BoardMemberFactory)
