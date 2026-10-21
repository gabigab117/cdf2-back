"""What the stock leaves to the board, in its bell and its sidebar (A6, 7.1)."""

from decimal import Decimal

import pytest

from stock.models import StockOperationReason
from tests.helpers import iso, member_json
from tests.stock.factories import (
    StockItemFactory,
    StockMovementFactory,
    StockOperationFactory,
    bought,
    moved,
)
from tests.stock.mockup import LOW, build_mockup

pytestmark = pytest.mark.django_db

OVERVIEW = "/api/board/overview"


def pending(client):
    return client.get(OVERVIEW).json()["pending"]


def test_the_bell_lists_the_items_below_their_threshold(board_client):
    """
    Given the fourteen items of the mockup
    When a member opens the bell
    Then the juice, the sweets and the fries await, in the stock's order, each
    with its quantity, its threshold and its unit; the kegs at their threshold
    do not
    """
    items = build_mockup()

    stock = pending(board_client)["stock"]

    assert stock["count"] == 3
    assert [item["name"] for item in stock["items"]] == LOW
    assert stock["items"][1] == {
        "id": items["Bonbons assortis"].pk,
        "name": "Bonbons assortis",
        "unit": "kg",
        "quantity": "1.50",
        "threshold": "3.00",
    }


def test_the_bell_lists_ten_low_items_at_most(board_client):
    """
    Given twelve items with nothing in stock
    When a member opens the bell
    Then the twelve await, and ten are listed
    """
    StockItemFactory.create_batch(12)

    stock = pending(board_client)["stock"]

    assert (stock["count"], len(stock["items"])) == (12, 10)


def test_the_low_items_count_among_what_awaits_the_board(board_client):
    """
    Given two items with nothing in stock, and one well above its threshold
    When a member opens the dashboard
    Then the two low items are counted among what awaits the board
    """
    StockItemFactory.create_batch(2)
    bought(StockItemFactory(), 200, "120.00")

    assert pending(board_client)["total"] == 2


def test_the_bell_asks_for_the_purchases_waiting_for_their_cost(board_client, board_member):
    """
    Given the shopping of the bar with a line of no cost, then a delivery of no
    cost; a purchase whose lines all have one, and a consumption
    When a member opens the bell
    Then the shopping and the delivery wait for their cost, the oldest first,
    each with its label and its member, and count among what awaits the board
    """
    cans = StockItemFactory(threshold=Decimal(0))
    water = StockItemFactory(threshold=Decimal(0))
    shopping = StockOperationFactory(label="Courses buvette", author=board_member)
    StockMovementFactory(operation=shopping, item=cans, cost=Decimal("26.40"))
    StockMovementFactory(operation=shopping, item=water)
    delivery = StockOperationFactory(reason=StockOperationReason.DELIVERY, label="Commande")
    StockMovementFactory(operation=delivery, item=cans)
    bought(water, 24, "6.00")
    moved(cans, -6, StockOperationReason.CONSUMPTION)

    body = pending(board_client)

    assert body["unpriced_purchases"] == {
        "count": 2,
        "items": [
            {
                "id": shopping.pk,
                "reason": "purchase",
                "label": "Courses buvette",
                "created_at": iso(shopping.created_at),
                "author": member_json(board_member),
            },
            {
                "id": delivery.pk,
                "reason": "delivery",
                "label": "Commande",
                "created_at": iso(delivery.created_at),
                "author": None,
            },
        ],
    }
    assert body["total"] == 2


def test_the_bell_lists_ten_purchases_waiting_for_their_cost_at_most(board_client):
    """
    Given twelve purchases of no cost
    When a member opens the bell
    Then the twelve wait, and ten are listed
    """
    StockMovementFactory.create_batch(12, item=StockItemFactory(threshold=Decimal(0)))

    unpriced = pending(board_client)["unpriced_purchases"]

    assert (unpriced["count"], len(unpriced["items"])) == (12, 10)
