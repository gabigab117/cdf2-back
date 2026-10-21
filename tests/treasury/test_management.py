"""The management control of a fiscal year (D16): the management result of
each event, the bar margin, the value of the stock and its losses, the
reconciliation, and what the figures wait for.
"""

import datetime as dt
from decimal import Decimal

import pytest

from stock.models import StockItemCategory, StockOperationReason
from tests.events.factories import EventFactory
from tests.helpers import iso
from tests.stock.factories import StockItemFactory, bought, moved, put_in_stock
from tests.treasury.factories import IncomeFactory, LedgerEntryFactory
from tests.treasury.scenario import PARIS, recorded, reference_scenario
from treasury.services.management import fiscal_year_management
from treasury.services.results import fiscal_year_results

pytestmark = pytest.mark.django_db

MANAGEMENT = "/api/board/treasury/management"
CONSUMPTION = StockOperationReason.CONSUMPTION
STOCKTAKE = StockOperationReason.STOCKTAKE


def management(year):
    return fiscal_year_management(fiscal_year_results(year))


def test_the_management_of_the_reference_scenario(mockup_day):
    """
    Given the reference scenario at the brocante
    When the treasurer reads the management control of 2026
    Then the brocante's result of 10,00 € makes a management result of
    19,40 €, its bar a margin of 43,00 €, 71,7 % of its takings
    And the general running loses the 1,13 € of the stocktake
    And the stock, worth nothing on 1 January, is worth 22,67 €: the adjusted
    result is 32,67 €, the management results and the 14,40 € no expense paid
    """
    brocante, cans = reference_scenario()

    report = management(2026)

    [row] = report.events
    assert (row.event.id, row.income, row.expense, row.stocked_purchases) == (
        brocante.pk,
        Decimal("60.00"),
        Decimal("50.00"),
        Decimal("26.40"),
    )
    assert (row.consumption_cost, row.management_result) == (Decimal("17.00"), Decimal("19.40"))
    assert (row.bar_margin, row.margin_rate, row.unlinked_purchases) == (
        Decimal("43.00"),
        Decimal("0.717"),
        Decimal("0.00"),
    )
    general = report.general
    assert (general.income, general.expense, general.stocked_purchases) == (0, 0, 0)
    assert (general.consumption_cost, general.management_result) == (
        Decimal("1.13"),
        Decimal("-1.13"),
    )
    assert (general.margin_rate, general.unlinked_purchases) == (None, Decimal("14.40"))
    totals = report.totals
    assert (totals.result, totals.opening_value, totals.closing_value) == (
        Decimal("10.00"),
        Decimal("0.00"),
        Decimal("22.67"),
    )
    assert (totals.stock_change, totals.adjusted_result, totals.management_result) == (
        Decimal("22.67"),
        Decimal("32.67"),
        Decimal("18.27"),
    )
    reconciliation = report.reconciliation
    assert (
        reconciliation.management_result,
        reconciliation.unlinked_purchases,
        reconciliation.paid_another_year,
        reconciliation.recorded_another_year,
        reconciliation.adjusted_result,
    ) == (Decimal("18.27"), Decimal("14.40"), 0, 0, Decimal("32.67"))
    assert [(value.category, value.value) for value in report.stock.categories] == [
        ("drinks", Decimal("22.67")),
        ("food", 0),
        ("supplies", 0),
        ("lotto_raffle", 0),
    ]
    assert report.stock.losses.total == Decimal("1.13")
    assert [(loss.item, loss.quantity, loss.value) for loss in report.stock.losses.items] == [
        (cans, Decimal(2), Decimal("1.13"))
    ]
    controls = report.controls
    assert (controls.unpriced_purchases, controls.unlinked_purchases, controls.unvalued_items) == (
        0,
        1,
        0,
    )


def test_the_management_control_through_the_api(board_client, mockup_day):
    """
    Given the reference scenario at the brocante
    When a member reads the management control of 2026
    Then the API gives its figures as the treasury gives amounts, the brocante
    named as its results name it
    """
    brocante, cans = reference_scenario()

    response = board_client.get(MANAGEMENT, {"year": 2026})

    assert response.status_code == 200
    body = response.json()
    assert (body["year"], body["years"]) == (2026, [2026])
    brocante.refresh_from_db()
    assert body["events"] == [
        {
            "event": {"id": brocante.pk, "title": "Brocante", "starts_at": iso(brocante.starts_at)},
            "income": "60.00",
            "expense": "50.00",
            "stocked_purchases": "26.40",
            "consumption_cost": "17.00",
            "management_result": "19.40",
            "bar_margin": "43.00",
            "margin_rate": "0.717",
            "unlinked_purchases": "0.00",
        }
    ]
    assert body["general"]["event"] is None
    assert body["totals"] == {
        "result": "10.00",
        "opening_value": "0.00",
        "closing_value": "22.67",
        "stock_change": "22.67",
        "adjusted_result": "32.67",
        "management_result": "18.27",
    }
    assert body["stock"]["losses"] == {
        "total": "1.13",
        "items": [
            {
                "item": {"id": cans.pk, "name": "Canettes de soda 33 cl", "unit": ""},
                "quantity": "2.00",
                "value": "1.13",
            }
        ],
    }
    assert body["reconciliation"] == {
        "management_result": "18.27",
        "unlinked_purchases": "14.40",
        "paid_another_year": "0.00",
        "recorded_another_year": "0.00",
        "adjusted_result": "32.67",
    }
    assert body["controls"] == {
        "unpriced_purchases": 0,
        "unlinked_purchases": 1,
        "unvalued_items": 0,
    }


def test_reading_the_management_control_takes_a_fixed_number_of_queries(
    board_client, mockup_day, django_assert_max_num_queries
):
    reference_scenario()
    loto = EventFactory(title="Loto", starts_at=dt.datetime(2026, 10, 4, 14, tzinfo=PARIS))
    recorded(
        moved(StockItemFactory(), -1, CONSUMPTION), dt.datetime(2026, 10, 4, 18, tzinfo=PARIS), loto
    )

    # Authentication (2), the results by event, the years, the items, the
    # movements, the expenses that paid a purchase, the bar income, and the
    # events that have operations but no entry.
    with django_assert_max_num_queries(9):
        board_client.get(MANAGEMENT, {"year": 2026})


def test_an_event_without_bar_income_has_no_margin_rate(mockup_day):
    """
    Given a loto whose volunteers drank 12 cans worth 6,60 €, and which took
    no money at a bar
    When the management control is read
    Then the loto comes, though it has no entry, its bar margin of minus 6,60 € and no
    margin rate
    """
    loto = EventFactory(title="Loto", starts_at=dt.datetime(2026, 10, 4, 14, tzinfo=PARIS))
    cans = StockItemFactory()
    recorded(bought(cans, 48, "26.40"), dt.datetime(2026, 10, 1, 10, tzinfo=PARIS))
    recorded(moved(cans, -12, CONSUMPTION), dt.datetime(2026, 10, 4, 18, tzinfo=PARIS), loto)

    [row] = management(2026).events

    assert (row.event.title, row.income, row.consumption_cost) == ("Loto", 0, Decimal("6.60"))
    assert (row.management_result, row.bar_margin, row.margin_rate) == (
        Decimal("-6.60"),
        Decimal("-6.60"),
        None,
    )


def test_the_supplies_stay_out_of_the_bar_margin(mockup_day):
    """
    Given the brocante's bar, which took 60,00 € and served cans and cups
    When the management control is read
    Then the cans come off its bar margin, the cups only off its result
    """
    brocante = EventFactory(title="Brocante", starts_at=dt.datetime(2026, 9, 13, 7, tzinfo=PARIS))
    cans = StockItemFactory()
    cups = StockItemFactory(name="Gobelets", category=StockItemCategory.SUPPLIES)
    recorded(bought(cans, 48, "26.40"), dt.datetime(2026, 9, 12, 10, tzinfo=PARIS))
    recorded(bought(cups, 100, "5.00"), dt.datetime(2026, 9, 12, 10, 5, tzinfo=PARIS))
    recorded(moved(cans, -30, CONSUMPTION), dt.datetime(2026, 9, 13, 18, tzinfo=PARIS), brocante)
    recorded(moved(cups, -40, CONSUMPTION), dt.datetime(2026, 9, 13, 18, 5, tzinfo=PARIS), brocante)
    IncomeFactory(amount=Decimal("60.00"), event=brocante, date=dt.date(2026, 9, 13))

    [row] = management(2026).events

    assert (row.consumption_cost, row.bar_margin) == (Decimal("18.50"), Decimal("43.50"))


def test_a_closed_year_and_the_next_share_the_value_of_the_stock(mockup_day):
    """
    Given 48 cans bought in December 2025 for 26,40 €, no expense paying them,
    and 30 consumed in January 2026 with no event
    When the management control of each year is read
    Then 2025 ends with 26,40 € of stock, which 2026 opens with, and ends
    with 9,90 €: each year's reconciliation gives its adjusted result
    """
    cans = StockItemFactory()
    recorded(bought(cans, 48, "26.40"), dt.datetime(2025, 12, 20, 10, tzinfo=PARIS))
    recorded(moved(cans, -30, CONSUMPTION), dt.datetime(2026, 1, 10, 10, tzinfo=PARIS))

    closed, current = management(2025), management(2026)

    assert (closed.totals.opening_value, closed.totals.closing_value) == (0, Decimal("26.40"))
    assert (closed.reconciliation.unlinked_purchases, closed.totals.adjusted_result) == (
        Decimal("26.40"),
        Decimal("26.40"),
    )
    assert (current.totals.opening_value, current.totals.closing_value) == (
        Decimal("26.40"),
        Decimal("9.90"),
    )
    assert (current.general.consumption_cost, current.totals.adjusted_result) == (
        Decimal("16.50"),
        Decimal("-16.50"),
    )
    for report in (closed, current):
        assert report.reconciliation.adjusted_result == report.totals.adjusted_result


def test_a_purchase_paid_in_one_year_and_recorded_in_the_next(mockup_day):
    """
    Given the shopping of 30 December 2025, 50,00 €, which pays 48 cans put in
    stock on 2 January 2026 for 26,40 €
    When the management control of each year is read
    Then 2025 counts them in its stocked purchases, less in its reconciliation,
    and 2026 adds them, as a purchase an expense of another year paid
    """
    shopping = LedgerEntryFactory(amount=Decimal("50.00"), date=dt.date(2025, 12, 30))
    shopping.stock_purchase = recorded(
        bought(StockItemFactory(), 48, "26.40"), dt.datetime(2026, 1, 2, 10, tzinfo=PARIS)
    )
    shopping.save()

    closed, current = management(2025), management(2026)

    assert (closed.general.stocked_purchases, closed.reconciliation.recorded_another_year) == (
        Decimal("26.40"),
        Decimal("-26.40"),
    )
    assert current.reconciliation.paid_another_year == Decimal("26.40")
    assert current.reconciliation.unlinked_purchases == 0
    for report in (closed, current):
        assert report.reconciliation.adjusted_result == report.totals.adjusted_result


def test_the_controls_count_what_the_figures_wait_for(mockup_day):
    """
    Given a purchase of cans without its cost, a lot of prizes given at 0 €,
    and sweets put in stock before the costs, of no cost to come at
    When the management control is read
    Then one purchase waits for its cost, none for an expense, and the sweets
    are not valued
    """
    cans = StockItemFactory(initial_cost=Decimal("0.55"))
    recorded(put_in_stock(cans, 24), dt.datetime(2026, 9, 1, 10, tzinfo=PARIS))
    prizes = StockItemFactory(name="Lots", category=StockItemCategory.LOTTO_RAFFLE)
    recorded(bought(prizes, 10, "0.00"), dt.datetime(2026, 9, 2, 10, tzinfo=PARIS))
    sweets = StockItemFactory(name="Bonbons", category=StockItemCategory.FOOD)
    recorded(
        moved(sweets, 5, StockOperationReason.ADJUSTMENT), dt.datetime(2026, 9, 3, tzinfo=PARIS)
    )

    controls = management(2026).controls

    assert (controls.unpriced_purchases, controls.unlinked_purchases, controls.unvalued_items) == (
        1,
        1,
        1,
    )


def test_the_losses_of_an_item_not_valued_have_no_value(mockup_day):
    """
    Given sweets of no cost to come at, of which a stocktake finds 2 missing,
    and cans of which a stocktake finds 1 more than counted
    When the management control is read
    Then the sweets' loss has no value, and the can found comes as a loss
    below zero
    """
    sweets = StockItemFactory(name="Bonbons", category=StockItemCategory.FOOD)
    recorded(
        moved(sweets, 10, StockOperationReason.ADJUSTMENT), dt.datetime(2026, 9, 1, tzinfo=PARIS)
    )
    recorded(moved(sweets, -2, STOCKTAKE), dt.datetime(2026, 9, 20, tzinfo=PARIS))
    cans = StockItemFactory(name="Canettes")
    recorded(bought(cans, 48, "26.40"), dt.datetime(2026, 9, 1, 10, tzinfo=PARIS))
    recorded(moved(cans, 1, STOCKTAKE), dt.datetime(2026, 9, 20, 10, tzinfo=PARIS))

    losses = management(2026).stock.losses

    assert [(loss.item.name, loss.quantity, loss.value) for loss in losses.items] == [
        ("Bonbons", Decimal(2), None),
        ("Canettes", Decimal(-1), Decimal("-0.55")),
    ]
    assert losses.total == Decimal("-0.55")


def test_a_margin_rate_is_rounded_half_up(mockup_day):
    """
    Given a loto whose bar took 80,00 € and sold 46 cans worth 23,00 €
    When the management control is read
    Then its margin of 57,00 € is 71,25 % of its takings, rounded up to 71,3 %
    """
    loto = EventFactory(title="Loto", starts_at=dt.datetime(2026, 10, 4, 14, tzinfo=PARIS))
    cans = StockItemFactory()
    recorded(bought(cans, 46, "23.00"), dt.datetime(2026, 10, 1, 10, tzinfo=PARIS))
    recorded(moved(cans, -46, CONSUMPTION), dt.datetime(2026, 10, 4, 18, tzinfo=PARIS), loto)
    IncomeFactory(amount=Decimal("80.00"), event=loto, date=dt.date(2026, 10, 4))

    [row] = management(2026).events

    assert (row.bar_margin, row.margin_rate) == (Decimal("57.00"), Decimal("0.713"))
