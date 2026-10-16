"""What a fiscal year brought in and cost (A18): in all, for each event that has
entries, and for the committee's general running.

A fiscal year is a calendar year: an entry counts in the year of its date.
"""

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from django.db.models import Count, F, Q, Sum
from django.utils import timezone

from treasury.models import LedgerEntry, LedgerEntryKind

ZERO = Decimal("0.00")


@dataclass(frozen=True)
class LedgerTotals:
    income: Decimal
    expense: Decimal
    count: int

    @property
    def result(self) -> Decimal:
        return self.income - self.expense


@dataclass(frozen=True)
class LedgerEvent:
    id: int
    title: str
    starts_at: dt.datetime


@dataclass(frozen=True)
class LedgerEventResult(LedgerTotals):
    event: LedgerEvent


@dataclass(frozen=True)
class FiscalYearResults:
    year: int
    years: list[int]
    totals: LedgerTotals
    events: list[LedgerEventResult]
    general: LedgerTotals


def fiscal_year_results(year: int) -> FiscalYearResults:
    """The totals of a fiscal year: those of each event that has entries in it,
    the first to start first, then those of the general running.
    """
    rows = (
        LedgerEntry.objects.filter(date__year=year)
        .values("event", "event__title", "event__starts_at")
        .annotate(
            income=Sum("amount", filter=Q(kind=LedgerEntryKind.INCOME), default=ZERO),
            expense=Sum("amount", filter=Q(kind=LedgerEntryKind.EXPENSE), default=ZERO),
            count=Count("pk"),
        )
        # A grouped query ignores Meta.ordering: the events are ordered here.
        .order_by(F("event__starts_at").asc(nulls_last=True), "event")
    )
    events = []
    general = LedgerTotals(income=ZERO, expense=ZERO, count=0)
    for row in rows:
        sums = {"income": row["income"], "expense": row["expense"], "count": row["count"]}
        if row["event"] is None:
            general = LedgerTotals(**sums)
        else:
            event = LedgerEvent(row["event"], row["event__title"], row["event__starts_at"])
            events.append(LedgerEventResult(event=event, **sums))
    every = [*events, general]
    totals = LedgerTotals(
        income=sum((part.income for part in every), ZERO),
        expense=sum((part.expense for part in every), ZERO),
        count=sum(part.count for part in every),
    )
    return FiscalYearResults(
        year=year, years=fiscal_years(), totals=totals, events=events, general=general
    )


def fiscal_years() -> list[int]:
    """The years that have entries, and the current one in Paris, the latest first."""
    years = {day.year for day in LedgerEntry.objects.dates("date", "year")}
    return sorted(years | {timezone.localdate().year}, reverse=True)
