import datetime as dt
from decimal import Decimal

import pytest

from stock.models import StockItemCategory, StockOperation, StockOperationReason
from stock.services.valuation import ItemValuation, item_valuation, valued_movements
from tests.stock.factories import StockItemFactory, bought, moved, put_in_stock

pytestmark = pytest.mark.django_db

CONSUMPTION = StockOperationReason.CONSUMPTION
ADJUSTMENT = StockOperationReason.ADJUSTMENT
STOCKTAKE = StockOperationReason.STOCKTAKE


def history(item):
    """An item's movements, valued in their order."""
    return valued_movements([item.pk])[item.pk]


def valuation(item):
    return item_valuation(item, valued_movements([item.pk]).get(item.pk, []))


def cans_bought_twice():
    """48 cans bought for 26,40 €, 0,55 € each, then 24 for 14,40 €, 0,60 €."""
    cans = StockItemFactory(name="Canettes de soda 33 cl")
    bought(cans, 48, "26.40")
    bought(cans, 24, "14.40")
    return cans


def test_two_purchases_at_two_costs_make_a_weighted_average():
    """
    Given 48 cans bought for 26,40 €, then 24 for 14,40 €
    When the stock is valued
    Then the 72 cans are worth 40,80 €, at 0,5667 € on average, and the latest
    purchase paid cost 0,60 € a can
    """
    cans = cans_bought_twice()

    assert valuation(cans) == ItemValuation(
        value=Decimal("40.80"), average_cost=Decimal("0.5667"), last_unit_cost=Decimal("0.6000")
    )


def test_what_leaves_the_stock_goes_at_the_average_of_its_time():
    """
    Given the 72 cans worth 40,80 €
    When 30 are consumed, then a stocktake finds 40 of the 42 left
    Then the consumption takes 17,00 €, at 0,5667 € a can, the stocktake
    1,13 €, and the 40 cans left are worth 22,67 €
    """
    cans = cans_bought_twice()
    moved(cans, -30, CONSUMPTION)
    moved(cans, -2, STOCKTAKE)

    consumption, stocktake = history(cans)[2:]

    assert (consumption.value, consumption.unit_cost, consumption.value_after) == (
        Decimal("-17.00"),
        Decimal("0.5667"),
        Decimal("23.80"),
    )
    assert (stocktake.value, stocktake.quantity_after, stocktake.value_after) == (
        Decimal("-1.13"),
        Decimal(40),
        Decimal("22.67"),
    )
    assert stocktake.average_cost_after == Decimal("0.5668")


def test_an_exit_that_empties_the_stock_takes_all_its_value():
    """
    Given 3 bottles of syrup bought for 10,00 €, at 3,3333 € each
    When one is drunk, then the two left
    Then the first takes 3,33 €, the two others 6,67 €: no value is left over
    """
    syrup = StockItemFactory()
    bought(syrup, 3, "10.00")
    moved(syrup, -1, CONSUMPTION)
    moved(syrup, -2, CONSUMPTION)

    first, last = history(syrup)[1:]

    assert (first.value, last.value, last.value_after) == (
        Decimal("-3.33"),
        Decimal("-6.67"),
        Decimal("0.00"),
    )
    assert last.average_cost_after is None


def test_an_entry_without_a_cost_comes_at_the_average():
    """
    Given 24 cans bought for 14,40 €
    When a member adds 6 with the plus button, then records a purchase of 24
    that waits for its cost
    Then both come at 0,60 € a can, the average of their time; the purchase
    waits for its cost
    """
    cans = StockItemFactory()
    bought(cans, 24, "14.40")
    moved(cans, 6, ADJUSTMENT)
    put_in_stock(cans, 24)

    _bought, plus, purchase = history(cans)

    assert (plus.value, plus.unpriced) == (Decimal("3.60"), False)
    assert (purchase.value, purchase.unpriced, purchase.average_cost_after) == (
        Decimal("14.40"),
        True,
        Decimal("0.6000"),
    )


def test_an_entry_into_an_empty_stock_comes_at_the_latest_average():
    """
    Given 24 cans bought for 14,40 €, all drunk since
    When a member adds 6 with the plus button
    Then they come at 0,60 € a can, the latest average
    """
    cans = StockItemFactory()
    bought(cans, 24, "14.40")
    moved(cans, -24, CONSUMPTION)
    moved(cans, 6, ADJUSTMENT)

    assert history(cans)[-1].value == Decimal("3.60")
    assert valuation(cans).average_cost == Decimal("0.6000")


def test_the_stock_of_before_the_costs_comes_at_the_initial_cost():
    """
    Given cans at a starting cost of 0,50 €, 10 of them entered by hand
    When 24 are then bought for 14,40 €
    Then the 10 came at 5,00 €, and the 34 cans are worth 19,40 €
    """
    cans = StockItemFactory(initial_cost=Decimal("0.5"))
    moved(cans, 10, ADJUSTMENT)
    bought(cans, 24, "14.40")

    assert history(cans)[0].value == Decimal("5.00")
    assert valuation(cans).value == Decimal("19.40")


def test_without_an_initial_cost_the_stock_of_before_comes_at_the_first_purchase_paid():
    """
    Given 10 cans entered by hand, then 6 given as a prize, then 24 bought for
    14,40 €
    When the stock is valued
    Then the 10 came at 0,60 € a can, the cost of the first purchase paid: a
    prize given tells nothing of what the stock of before cost
    """
    cans = StockItemFactory()
    moved(cans, 10, ADJUSTMENT)
    bought(cans, 6, "0")
    bought(cans, 24, "14.40")

    by_hand, given, paid = history(cans)

    assert (by_hand.value, given.value, paid.value_after) == (
        Decimal("6.00"),
        Decimal(0),
        Decimal("20.40"),
    )


def test_prizes_given_are_worth_nothing():
    """
    Given 20 raffle prizes given to the committee, at 0 €
    When the stock is valued
    Then they are worth nothing, at 0 € each, and no purchase was paid
    """
    prizes = StockItemFactory(category=StockItemCategory.LOTTO_RAFFLE)
    bought(prizes, 20, "0")

    assert valuation(prizes) == ItemValuation(
        value=Decimal(0), average_cost=Decimal(0), last_unit_cost=None
    )


def test_an_item_without_a_cost_to_come_at_is_not_valued():
    """
    Given 12 kegs entered by hand, without a starting cost, never bought at a
    cost, 2 of them drunk since
    When the stock is valued
    Then neither the kegs nor what left them has a value
    """
    kegs = StockItemFactory()
    moved(kegs, 12, ADJUSTMENT)
    moved(kegs, -2, CONSUMPTION)

    entered, drunk = history(kegs)

    assert (entered.value, entered.unit_cost, drunk.value, drunk.value_after) == (
        None,
        None,
        None,
        None,
    )
    assert valuation(kegs) == ItemValuation(value=None, average_cost=None, last_unit_cost=None)


def test_an_item_never_moved_is_worth_nothing_at_its_initial_cost():
    """
    Given cans just added, at a starting cost of 0,50 €
    When the stock is valued
    Then they are worth nothing, and come at their starting cost
    """
    cans = StockItemFactory(initial_cost=Decimal("0.5"))

    assert valuation(cans) == ItemValuation(
        value=Decimal(0), average_cost=Decimal("0.5"), last_unit_cost=None
    )


def test_correcting_a_cost_values_everything_again():
    """
    Given 48 cans bought for 26,40 €, then 30 of them consumed
    When the cost of the purchase is corrected to 28,80 €
    Then the consumption, valued again, took 18,00 €
    """
    cans = StockItemFactory()
    purchase = bought(cans, 48, "26.40")
    moved(cans, -30, CONSUMPTION)

    purchase.cost = Decimal("28.80")
    purchase.save()

    assert history(cans)[1].value == Decimal("-18.00")


def test_the_movements_are_valued_in_the_order_they_were_recorded():
    """
    Given 10 cans bought for 10,00 €, then 10 for 30,00 €, then 10 consumed,
    the first purchase written last to the database
    When the stock is valued
    Then the consumption comes after both purchases, at 2,00 € a can: the order
    is the one of their recording, not of their keys
    """
    cans = StockItemFactory()
    dearer = bought(cans, 10, "30.00")
    consumption = moved(cans, -10, CONSUMPTION)
    cheaper = bought(cans, 10, "10.00")
    recorded = dearer.operation.created_at
    StockOperation.objects.filter(pk=cheaper.operation_id).update(
        created_at=recorded - dt.timedelta(minutes=1)
    )
    StockOperation.objects.filter(pk=consumption.operation_id).update(
        created_at=recorded + dt.timedelta(minutes=1)
    )

    assert [movement.value for movement in history(cans)] == [
        Decimal("10.00"),
        Decimal("30.00"),
        Decimal("-20.00"),
    ]


def test_the_stock_is_valued_in_one_query(django_assert_num_queries):
    """
    Given cans and syrup, each bought and consumed
    When the whole stock is valued
    Then it takes a single query, whatever its movements
    """
    for item in (StockItemFactory(), StockItemFactory()):
        bought(item, 24, "14.40")
        moved(item, -6, CONSUMPTION)

    with django_assert_num_queries(1):
        histories = valued_movements()

    assert sorted(len(movements) for movements in histories.values()) == [2, 2]
