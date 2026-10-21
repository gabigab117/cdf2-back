from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from stock.models import StockItem, StockMovement, StockOperation, StockOperationReason
from tests.events.factories import EventFactory
from tests.helpers import iso, member_json, messages_by_place, send
from tests.stock.factories import (
    StockItemFactory,
    StockMovementFactory,
    StockOperationFactory,
    put_in_stock,
    quantity_of,
)

pytestmark = pytest.mark.django_db

STOCK = "/api/board/stock"
OPERATIONS_PATH = f"{STOCK}/operations"
STOCKTAKES = f"{STOCK}/stocktakes"


def entry(*lines, direction="in", reason="purchase", label="Courses buvette", event=None):
    """An entry or an exit as its form sends it, whole: its lines are (item, quantity)."""
    return {
        "direction": direction,
        "reason": reason,
        "label": label,
        "event": event,
        "lines": [{"item": item.pk, "quantity": str(quantity)} for item, quantity in lines],
    }


def stocktake(*counts, label="", event=None):
    """A stocktake as its form sends it: its counts are (item, counted)."""
    return {
        "label": label,
        "event": event,
        "counts": [{"item": item.pk, "counted": str(counted)} for item, counted in counts],
    }


# Entries and exits


def test_a_purchase_brings_several_items_in(board_client, board_member):
    """
    Given cans and water in stock
    When a member records the shopping of the bar for the brocante
    Then both come in, in a single purchase of the member, which the API tells
    """
    brocante = EventFactory(title="Brocante")
    cans = StockItemFactory(name="Canettes de soda 33 cl")
    water = StockItemFactory(name="Bouteilles d’eau 50 cl")
    put_in_stock(cans, 144)

    response = send(
        board_client, "post", OPERATIONS_PATH, entry((cans, 288), (water, 120), event=brocante.pk)
    )

    assert response.status_code == 201
    operation = StockOperation.objects.get(
        reason=StockOperationReason.PURCHASE, author=board_member
    )
    assert response.json() == {
        "id": operation.pk,
        "reason": "purchase",
        "label": "Courses buvette",
        "event": {"id": brocante.pk, "title": "Brocante"},
        "author": member_json(board_member),
        "created_at": iso(operation.created_at),
        "movements": [
            {
                "item": {"id": cans.pk, "name": "Canettes de soda 33 cl", "unit": ""},
                "delta": "288.00",
            },
            {
                "item": {"id": water.pk, "name": "Bouteilles d’eau 50 cl", "unit": ""},
                "delta": "120.00",
            },
        ],
    }
    assert (quantity_of(cans), quantity_of(water)) == (432, 120)


def test_a_purchase_tells_what_each_line_cost(board_client):
    """
    Given cans and water
    When a member records the shopping of the bar, the cans for 26,40 €, the
    water without its cost
    Then each line keeps what it cost, and the water waits for its cost
    """
    cans = StockItemFactory()
    water = StockItemFactory()
    body = entry((cans, 48), (water, 24))
    body["lines"][0]["cost"] = "26.40"

    response = send(board_client, "post", OPERATIONS_PATH, body)

    assert response.status_code == 201
    assert dict(StockMovement.objects.values_list("item", "cost")) == {
        cans.pk: Decimal("26.40"),
        water.pk: None,
    }


@pytest.mark.parametrize(
    ("reason", "direction", "cost", "message"),
    [
        ("consumption", "out", "3.00", "Seul un achat a un prix."),
        ("adjustment", "in", "3.00", "Seul un achat a un prix."),
        ("purchase", "in", "-1", "Assurez-vous que cette valeur est supérieure ou égale à 0."),
        (
            "purchase",
            "in",
            "2.125",
            "Assurez-vous qu’il n’y a pas plus de 2 chiffres après la virgule.",
        ),
    ],
)
def test_a_cost_out_of_rule_is_refused_under_its_line(
    board_client, reason, direction, cost, message
):
    """
    Given cans in stock
    When an entry or an exit gives a line a cost, though it is no purchase; or a
    purchase gives one below zero, or finer than the cent
    Then it is refused under the cost of its line, and nothing is recorded
    """
    cans = StockItemFactory()
    put_in_stock(cans, 24)
    body = entry((cans, 2), direction=direction, reason=reason)
    body["lines"][0]["cost"] = cost

    response = send(board_client, "post", OPERATIONS_PATH, body)

    assert messages_by_place(response) == {("body", "lines", 0, "cost"): message}
    assert StockOperation.objects.count() == 1


def test_a_consumption_takes_items_out(board_client):
    """
    Given 432 cans in stock
    When a member records what the brocante drank
    Then the cans go out
    """
    cans = StockItemFactory()
    put_in_stock(cans, 432)

    response = send(
        board_client,
        "post",
        OPERATIONS_PATH,
        entry((cans, 216), direction="out", reason="consumption", label="Consommé à la brocante"),
    )

    assert response.status_code == 201
    assert response.json()["movements"][0]["delta"] == "-216.00"
    assert quantity_of(cans) == 216


@pytest.mark.parametrize(("direction", "left"), [("in", 26), ("out", 22)])
def test_an_adjustment_goes_either_way(board_client, direction, left):
    """
    Given 24 cans in stock
    When a member adjusts two of them in, or out
    Then the stock moves that way
    """
    cans = StockItemFactory()
    put_in_stock(cans, 24)

    response = send(
        board_client,
        "post",
        OPERATIONS_PATH,
        entry((cans, 2), direction=direction, reason="adjustment"),
    )

    assert response.status_code == 201
    assert quantity_of(cans) == left


@pytest.mark.parametrize(
    ("direction", "reason", "message"),
    [
        ("out", "purchase", "Un achat entre dans le stock."),
        ("in", "consumption", "Une consommation sort du stock."),
    ],
)
def test_a_purchase_comes_in_and_a_consumption_goes_out(board_client, direction, reason, message):
    """
    Given cans in stock
    When a purchase is sent out, or a consumption in
    Then it is refused under its reason
    """
    cans = StockItemFactory()
    put_in_stock(cans, 24)

    response = send(
        board_client, "post", OPERATIONS_PATH, entry((cans, 2), direction=direction, reason=reason)
    )

    assert messages_by_place(response) == {("body", "reason"): message}


@pytest.mark.parametrize("reason", ["stocktake", "delivery"])
def test_a_stocktake_and_a_delivery_have_their_own_screens(board_client, reason):
    """
    Given cans in stock
    When an entry gives the reason of a stocktake or a delivery
    Then the schema refuses it
    """
    response = send(
        board_client, "post", OPERATIONS_PATH, entry((StockItemFactory(), 2), reason=reason)
    )

    assert messages_by_place(response) == {
        ("body", "payload", "reason"): (
            "Sélectionnez un choix valide. Ce choix ne fait pas partie de ceux disponibles."
        )
    }


def test_an_entry_without_any_line_is_refused(board_client):
    """
    Given a member of the board
    When they record an entry without any line
    Then it is refused, asking for an item
    """
    response = send(board_client, "post", OPERATIONS_PATH, entry())

    assert messages_by_place(response) == {("body",): "Ajoutez au moins un article."}


def test_each_line_out_of_rule_is_refused_under_its_position(board_client):
    """
    Given cans and water in stock
    When an entry names an item that does not exist, the cans twice, nothing
    of the water, and a quantity finer than the hundredth
    Then each line is refused under its own position, the operation's own
    fields too, and nothing is recorded
    """
    cans = StockItemFactory()
    water = StockItemFactory()
    body = entry((cans, 2), (water, 0), (cans, "0.125"), event=999)
    body["lines"].append({"item": 999, "quantity": "1"})

    response = send(board_client, "post", OPERATIONS_PATH, body)

    assert messages_by_place(response) == {
        ("body", "event"): "Choisissez un événement existant.",
        ("body", "lines", 1, "quantity"): "Indiquez une quantité supérieure à zéro.",
        ("body", "lines", 2, "item"): "Cet article figure déjà dans l’opération.",
        ("body", "lines", 2, "quantity"): (
            "Assurez-vous qu’il n’y a pas plus de 2 chiffres après la virgule."
        ),
        ("body", "lines", 3, "item"): "Choisissez un article existant.",
    }
    assert not StockOperation.objects.exists()


@pytest.mark.parametrize(
    ("unit", "held", "message"),
    [
        ("", 18, "Il n’en reste que 18 en stock."),
        ("kg", "1.5", "Il n’en reste que 1,5\u00a0kg en stock."),
        ("", 0, "Il n’en reste plus en stock."),
    ],
)
def test_an_exit_never_takes_more_than_is_in_stock(board_client, unit, held, message):
    """
    Given 18 litres of juice, 1,5 kg of sweets, or nothing left
    When a member takes out more
    Then the line is refused, saying what is left with its unit, and nothing
    goes out
    """
    item = StockItemFactory(unit=unit)
    if held:
        put_in_stock(item, held)
    cans = StockItemFactory()
    put_in_stock(cans, 48)

    response = send(
        board_client,
        "post",
        OPERATIONS_PATH,
        entry((cans, 24), (item, 20), direction="out", reason="consumption"),
    )

    assert messages_by_place(response) == {("body", "lines", 1, "quantity"): message}
    assert quantity_of(cans) == 48


def test_an_exit_may_take_all_that_is_left(board_client):
    """
    Given 18 litres of juice
    When a member takes the 18 out
    Then nothing is left, and nothing is refused
    """
    juice = StockItemFactory()
    put_in_stock(juice, 18)

    response = send(
        board_client,
        "post",
        OPERATIONS_PATH,
        entry((juice, 18), direction="out", reason="consumption"),
    )

    assert response.status_code == 201
    assert quantity_of(juice) == 0


def test_an_exit_locks_its_items_by_key_before_reading_the_stock(board_client):
    """
    Given cans and water in stock
    When a member takes both out
    Then the items are locked first, by key, then their stock is summed: two
    exits at once never take more than is left
    """
    water = StockItemFactory()
    cans = StockItemFactory()
    put_in_stock(water, 24)
    put_in_stock(cans, 24)

    with CaptureQueriesContext(connection) as queries:
        send(
            board_client,
            "post",
            OPERATIONS_PATH,
            entry((cans, 1), (water, 1), direction="out", reason="consumption"),
        )

    statements = [query["sql"] for query in queries.captured_queries]
    [lock] = [index for index, sql in enumerate(statements) if "FOR UPDATE" in sql]
    summing = next(index for index, sql in enumerate(statements) if "SUM(" in sql)
    assert StockItem._meta.db_table in statements[lock]
    assert f'ORDER BY "{StockItem._meta.db_table}"."id" ASC' in statements[lock]
    assert lock < summing


# Stocktakes


def test_a_stocktake_turns_each_difference_into_a_movement(board_client, board_member):
    """
    Given 432 cans, 120 bottles of water and 30 bags of fries in stock
    When a member counts 216 cans, 120 bottles and 4 bags after the brocante,
    and does not count the juice
    Then a single stocktake of the member records what changed: 216 cans and
    26 bags out, the water as it was, the juice untouched
    """
    brocante = EventFactory(title="Brocante")
    cans, water, fries, juice = StockItemFactory.create_batch(4)
    put_in_stock(cans, 432)
    put_in_stock(water, 120)
    put_in_stock(fries, 30)
    put_in_stock(juice, 18)

    response = send(
        board_client,
        "post",
        STOCKTAKES,
        stocktake(
            (cans, 216), (water, 120), (fries, 4), label="Consommé à la brocante", event=brocante.pk
        ),
    )

    assert response.status_code == 201
    body = response.json()
    assert (body["reason"], body["label"], body["event"]["title"]) == (
        "stocktake",
        "Consommé à la brocante",
        "Brocante",
    )
    assert [(movement["item"]["id"], movement["delta"]) for movement in body["movements"]] == [
        (cans.pk, "-216.00"),
        (fries.pk, "-26.00"),
    ]
    assert StockOperation.objects.get(pk=body["id"]).author == board_member
    assert [quantity_of(item) for item in (cans, water, fries, juice)] == [216, 120, 4, 18]


def test_a_stocktake_may_find_more_than_the_stock_held(board_client):
    """
    Given 4 kegs in stock
    When 5 are counted
    Then one comes in
    """
    kegs = StockItemFactory()
    put_in_stock(kegs, 4)

    response = send(board_client, "post", STOCKTAKES, stocktake((kegs, 5)))

    assert response.json()["movements"][0]["delta"] == "1.00"


def test_a_stocktake_without_any_difference_still_dates_the_stock(board_client):
    """
    Given 24 cans in stock
    When 24 are counted
    Then the stocktake is recorded, without any movement, and dates the stock
    """
    cans = StockItemFactory()
    put_in_stock(cans, 24)

    response = send(board_client, "post", STOCKTAKES, stocktake((cans, 24)))

    assert response.status_code == 201
    assert response.json()["movements"] == []
    stocktake_made = StockOperation.objects.get(pk=response.json()["id"])
    assert board_client.get(STOCK).json()["last_stocktake"]["created_at"] == iso(
        stocktake_made.created_at
    )


def test_a_stocktake_counts_at_least_one_item(board_client):
    """
    Given a member of the board
    When they record a stocktake that counts no item
    Then it is refused, asking for one
    """
    response = send(board_client, "post", STOCKTAKES, stocktake())

    assert messages_by_place(response) == {("body",): "Comptez au moins un article."}


def test_each_count_out_of_rule_is_refused_under_its_position(board_client):
    """
    Given cans in stock
    When a stocktake counts below zero, then the cans twice, finer than the
    hundredth
    Then each count is refused under its own position
    """
    cans = StockItemFactory()

    response = send(board_client, "post", STOCKTAKES, stocktake((cans, -1), (cans, "0.125")))

    assert messages_by_place(response) == {
        (
            "body",
            "counts",
            0,
            "counted",
        ): "Assurez-vous que cette valeur est supérieure ou égale à 0.",
        ("body", "counts", 1, "item"): "Cet article figure déjà dans l’opération.",
        ("body", "counts", 1, "counted"): (
            "Assurez-vous qu’il n’y a pas plus de 2 chiffres après la virgule."
        ),
    }


# Recent operations


def test_the_stock_tells_its_five_latest_operations(board_client, board_member):
    """
    Given six operations, the latest a click on plus by a member
    When a member reads the stock
    Then the five latest come, the latest first, each with its movements in the
    order they were written
    """
    cans = StockItemFactory(name="Canettes", unit="")
    for index in range(5):
        put_in_stock(cans, index + 1)
    click = StockOperationFactory(reason=StockOperationReason.ADJUSTMENT, author=board_member)
    StockMovementFactory(operation=click, item=cans, delta=Decimal(24))

    recent = board_client.get(STOCK).json()["recent_operations"]

    assert len(recent) == 5
    assert recent[0] == {
        "id": click.pk,
        "reason": "adjustment",
        "label": "",
        "event": None,
        "author": member_json(board_member),
        "created_at": iso(click.created_at),
        "movements": [{"item": {"id": cans.pk, "name": "Canettes", "unit": ""}, "delta": "24.00"}],
    }
    assert [operation["movements"][0]["delta"] for operation in recent[1:]] == [
        "5.00",
        "4.00",
        "3.00",
        "2.00",
    ]
