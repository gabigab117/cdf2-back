"""What the stock leaves to the board, in its bell and its sidebar (A6, 7.1)."""

import pytest

from tests.stock.factories import StockItemFactory, put_in_stock
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
    put_in_stock(StockItemFactory(), 200)

    assert pending(board_client)["total"] == 2
