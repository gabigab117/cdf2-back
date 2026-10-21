"""The report of a fiscal year for the general meeting (6.6, A18): its totals
and results, what each category brought in or cost, and the receipts it misses;
its stock and the management result of each event (D16).
"""

from dataclasses import dataclass
from decimal import Decimal

from django.db.models import Count, Sum

from treasury.models import (
    EXPENSE_CATEGORIES,
    INCOME_CATEGORIES,
    LedgerEntry,
    LedgerEntryKind,
)
from treasury.services.entries import missing_receipts
from treasury.services.management import FiscalYearManagement, fiscal_year_management
from treasury.services.results import (
    LedgerEventResult,
    LedgerTotals,
    fiscal_year_results,
)


@dataclass(frozen=True)
class CategoryTotal:
    category: str
    total: Decimal
    count: int


@dataclass(frozen=True)
class GeneralMeetingReport:
    year: int
    totals: LedgerTotals
    events: list[LedgerEventResult]
    general: LedgerTotals
    income_categories: list[CategoryTotal]
    expense_categories: list[CategoryTotal]
    missing_receipts: list[LedgerEntry]
    # The stock on 1 January and at the end of the year, the adjusted result,
    # and each event's management result.
    management: FiscalYearManagement


def general_meeting_report(year: int) -> GeneralMeetingReport:
    """The report of a fiscal year: the categories that have entries in the
    order of the form, and the expenses missing their receipt, the oldest first.
    """
    results = fiscal_year_results(year)
    rows = (
        LedgerEntry.objects.filter(date__year=year)
        .values("kind", "category")
        .annotate(total=Sum("amount"), count=Count("pk"))
        # A grouped query ignores Meta.ordering: the categories are ordered below.
        .order_by()
    )
    sums = {(row["kind"], row["category"]): row for row in rows}
    return GeneralMeetingReport(
        year=year,
        totals=results.totals,
        events=results.events,
        general=results.general,
        income_categories=_ordered(sums, LedgerEntryKind.INCOME, INCOME_CATEGORIES),
        expense_categories=_ordered(sums, LedgerEntryKind.EXPENSE, EXPENSE_CATEGORIES),
        missing_receipts=list(missing_receipts().filter(date__year=year)),
        management=fiscal_year_management(results),
    )


def _ordered(sums: dict, kind: str, categories: tuple[str, ...]) -> list[CategoryTotal]:
    return [
        CategoryTotal(category, sums[kind, category]["total"], sums[kind, category]["count"])
        for category in categories
        if (kind, category) in sums
    ]
