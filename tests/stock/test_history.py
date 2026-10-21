from decimal import Decimal

import pytest

from stock.models import StockOperationReason
from tests.events.factories import EventFactory
from tests.helpers import iso
from tests.stock.factories import StockItemFactory, StockOperationFactory, bought, moved

pytestmark = pytest.mark.django_db

STOCK = "/api/board/stock"


def history_url(item_id):
    return f"{STOCK}/items/{item_id}/history"


def test_the_stock_card_tells_each_movement_valued_the_latest_first(board_client):
    """
    Given cans bought twice, 48 for 26,40 € then 24 for 14,40 €, then 30 of them
    drunk at the brocante
    When a member reads the cans' stock card
    Then the consumption comes first, at 0,5667 € a can, 17,00 € out, the stock
    left 42 cans worth 23,80 €; then each purchase, at its own cost, and the
    average it made
    """
    cans = StockItemFactory()
    first = bought(cans, 48, "26.40")
    bought(cans, 24, "14.40")
    brocante = EventFactory(title="Brocante")
    drunk = StockOperationFactory(reason=StockOperationReason.CONSUMPTION, event=brocante)
    drunk.movements.create(item=cans, delta=Decimal(-30))

    response = board_client.get(history_url(cans.pk))

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 3
    assert body["items"][0] == {
        "operation": {
            "id": drunk.pk,
            "reason": "consumption",
            "label": "",
            "created_at": iso(drunk.created_at),
            "event": {"id": brocante.pk, "title": "Brocante"},
        },
        "delta": "-30.00",
        "cost": None,
        "unit_cost": "0.5667",
        "value": "-17.00",
        "unpriced": False,
        "quantity_after": "42.00",
        "value_after": "23.80",
        "average_cost_after": "0.5667",
    }
    assert [
        (line["unit_cost"], line["value_after"], line["average_cost_after"])
        for line in body["items"][1:]
    ] == [("0.6000", "40.80", "0.5667"), ("0.5500", "26.40", "0.5500")]
    assert body["items"][2]["operation"]["id"] == first.operation_id


def test_the_stock_card_of_an_item_not_valued_tells_its_quantities(board_client):
    """
    Given kegs entered by hand, of no cost to come at
    When a member reads their stock card
    Then each movement tells the stock after it, and no value
    """
    kegs = StockItemFactory()
    moved(kegs, 10, StockOperationReason.ADJUSTMENT)

    [line] = board_client.get(history_url(kegs.pk)).json()["items"]

    assert (line["quantity_after"], line["value"], line["value_after"]) == ("10.00", None, None)


def test_the_stock_card_comes_by_page(board_client):
    """
    Given cans that moved thirty times
    When a member reads the second page of their stock card
    Then it holds the five oldest, of thirty
    """
    cans = StockItemFactory()
    for _ in range(30):
        bought(cans, 1, "0.50")

    body = board_client.get(history_url(cans.pk), {"page": 2}).json()

    assert (body["count"], len(body["items"])) == (30, 5)


def test_the_stock_card_takes_a_fixed_number_of_queries(
    board_client, django_assert_max_num_queries
):
    """
    Given cans that moved thirty times
    When a member reads their stock card
    Then it comes in a fixed number of queries, whatever its movements
    """
    cans = StockItemFactory()
    for _ in range(30):
        bought(cans, 1, "0.50")

    # Authentication (2), the item, its movements valued, their operations.
    with django_assert_max_num_queries(5):
        board_client.get(history_url(cans.pk))


def test_the_stock_card_of_an_item_that_does_not_exist_is_not_found(board_client):
    """
    Given no item of id 999
    When a member reads its stock card
    Then it is not found
    """
    assert board_client.get(history_url(999)).status_code == 404
