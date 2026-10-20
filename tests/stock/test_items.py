from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from stock.models import StockItem, StockMovement, StockOperation, StockOperationReason
from tests.accounts.factories import UserFactory, client_of
from tests.events.factories import EventFactory
from tests.helpers import iso, send
from tests.stock.factories import (
    StockItemFactory,
    StockOperationFactory,
    put_in_stock,
    quantity_of,
)
from tests.stock.mockup import LEVELS, LOW, build_mockup

pytestmark = pytest.mark.django_db

STOCK = "/api/board/stock"
ITEMS_PATH = f"{STOCK}/items"

# Every operation of the stock, the paths of a single item naming any id: a
# refusal comes before the item is looked up.
OPERATIONS = [
    ("get", STOCK),
    ("post", ITEMS_PATH),
    ("put", f"{ITEMS_PATH}/1"),
    ("delete", f"{ITEMS_PATH}/1"),
    ("post", f"{ITEMS_PATH}/1/adjustments"),
    ("post", f"{STOCK}/operations"),
    ("post", f"{STOCK}/stocktakes"),
    ("get", f"{STOCK}/orders/1"),
    ("put", f"{STOCK}/orders/1/lines"),
    ("post", f"{STOCK}/orders/1/delivery"),
    ("delete", f"{STOCK}/orders/1/delivery"),
]


def url(item_id):
    return f"{ITEMS_PATH}/{item_id}"


def payload(**changes):
    """An item as its form sends it, whole."""
    return {
        "name": "Jus de fruits 1 L",
        "category": "drinks",
        "unit": "",
        "threshold": "24",
        "step": "6",
        "best_before": None,
    } | changes


def adjust(client, item, direction):
    return send(client, "post", f"{url(item.pk)}/adjustments", {"direction": direction})


def refusal(field, message):
    location = ["body", field] if field else ["body"]
    return {"detail": [{"type": "validation_error", "loc": location, "msg": message}]}


# Access


@pytest.mark.parametrize(("method", "path"), OPERATIONS)
def test_the_stock_is_reserved_to_signed_in_members(client, method, path):
    """
    Given a visitor without an access token
    When they read or write the stock
    Then the API refuses with a 401
    """
    response = getattr(client, method)(path)

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentification requise."}


@pytest.mark.parametrize(("method", "path"), OPERATIONS)
def test_the_stock_is_refused_to_accounts_outside_the_board(method, path):
    """
    Given an active account outside the board
    When it reads or writes the stock
    Then the API refuses with a 403
    """
    response = getattr(client_of(UserFactory()), method)(path)

    assert response.status_code == 403
    assert response.json() == {"detail": "Accès réservé aux membres du bureau."}


# Reading


def test_the_stock_of_the_mockup_tells_the_items_below_their_threshold(board_client):
    """
    Given the fourteen items of the mockup
    When a member reads the stock
    Then the juice, the sweets and the fries are low, the kegs at their
    threshold are not, and each bar is full from its threshold up
    """
    build_mockup()

    items = board_client.get(STOCK).json()["items"]

    assert [entry["item"]["name"] for entry in items if entry["low"]] == LOW
    assert {entry["item"]["name"]: entry["level"] for entry in items} == LEVELS


def test_the_stock_comes_by_category_then_by_name_with_its_figures(board_client):
    """
    Given the fourteen items of the mockup
    When a member reads the stock
    Then they come in the order of the chips, then by name, and the chips are
    counted: in all, low, and by category
    """
    build_mockup()

    body = board_client.get(STOCK).json()

    assert [entry["item"]["name"] for entry in body["items"]] == [
        "Bouteilles d’eau 50 cl",
        "Café moulu 1 kg",
        "Canettes de soda 33 cl",
        "Fûts de bière 20 L",
        "Jus de fruits 1 L",
        "Bonbons assortis",
        "Frites surgelées 2,5 kg",
        "Sucre en morceaux 1 kg",
        "Barquettes à frites",
        "Gobelets carton",
        "Gobelets réutilisables",
        "Serviettes (paquets de 100)",
        "Carnets de tombola",
        "Cartons de loto",
    ]
    assert body["counts"] == {
        "total": 14,
        "low": 3,
        "drinks": 5,
        "food": 3,
        "supplies": 4,
        "lotto_raffle": 2,
    }


def test_an_item_tells_its_fields_and_its_quantity(board_client):
    """
    Given 1,5 kg of sweets, low below 3 kg, best before March 2027
    When a member reads the stock
    Then the item comes as its form writes it, with its quantity
    """
    items = build_mockup()
    sweets = items["Bonbons assortis"]

    [entry] = [
        entry
        for entry in board_client.get(STOCK).json()["items"]
        if entry["item"]["id"] == sweets.pk
    ]

    assert entry == {
        "item": {
            "id": sweets.pk,
            "name": "Bonbons assortis",
            "category": "food",
            "unit": "kg",
            "threshold": "3.00",
            "step": "0.50",
            "best_before": "2027-03-01",
        },
        "quantity": "1.50",
        "low": True,
        "level": 50,
    }


def test_an_item_never_moved_has_nothing_in_stock(board_client):
    """
    Given an item just added, and one whose threshold is zero
    When a member reads the stock
    Then the first has nothing, is low and its bar is empty; the second, with
    nothing either, is not low
    """
    StockItemFactory(name="Jus de fruits 1 L", threshold=Decimal(24))
    StockItemFactory(name="Sirop", threshold=Decimal(0))

    items = board_client.get(STOCK).json()["items"]

    assert [(entry["quantity"], entry["low"], entry["level"]) for entry in items] == [
        ("0.00", True, 0),
        ("0.00", False, 0),
    ]


def test_an_item_without_threshold_is_full_while_some_is_left(board_client):
    """
    Given some syrup, whose threshold is zero
    When a member reads the stock
    Then its bar is full, and it is not low
    """
    put_in_stock(StockItemFactory(threshold=Decimal(0)), 2)

    [entry] = board_client.get(STOCK).json()["items"]

    assert (entry["low"], entry["level"]) == (False, 100)


def test_the_stock_is_dated_by_its_latest_stocktake(board_client):
    """
    Given a stocktake after the brocante, then a later one of no event, and a
    later purchase
    When a member reads the stock
    Then the latest stocktake dates it, without event
    """
    StockOperationFactory(reason=StockOperationReason.STOCKTAKE, event=EventFactory())
    latest = StockOperationFactory(reason=StockOperationReason.STOCKTAKE)
    StockOperationFactory(reason=StockOperationReason.PURCHASE)

    body = board_client.get(STOCK).json()

    assert body["last_stocktake"] == {"created_at": iso(latest.created_at), "event": None}


def test_a_stocktake_names_its_event(board_client):
    """
    Given a stocktake after the brocante
    When a member reads the stock
    Then the stocktake names the brocante
    """
    brocante = EventFactory(title="Brocante")
    StockOperationFactory(reason=StockOperationReason.STOCKTAKE, event=brocante)

    stocktake = board_client.get(STOCK).json()["last_stocktake"]

    assert stocktake["event"] == {"id": brocante.pk, "title": "Brocante"}


def test_a_stocktake_stays_once_its_event_is_deleted(board_client):
    """
    Given a stocktake after the brocante
    When a member deletes the brocante
    Then the event goes, and the stocktake stays, without it
    """
    brocante = EventFactory(title="Brocante")
    StockOperationFactory(reason=StockOperationReason.STOCKTAKE, event=brocante)

    response = board_client.delete(f"/api/board/events/{brocante.pk}")

    assert response.status_code == 204
    assert board_client.get(STOCK).json()["last_stocktake"]["event"] is None


def test_the_stock_has_no_stocktake_before_the_first(board_client):
    """
    Given no stocktake ever made
    When a member reads the stock
    Then it is not dated, and holds no item yet
    """
    body = board_client.get(STOCK).json()

    assert body["last_stocktake"] is None
    assert body["items"] == []
    assert body["counts"]["total"] == 0


def test_the_stock_takes_a_fixed_number_of_queries(board_client, django_assert_max_num_queries):
    """
    Given the fourteen items of the mockup, each moved
    When a member reads the stock
    Then it comes in a fixed number of queries
    """
    build_mockup()
    StockOperationFactory(
        reason=StockOperationReason.STOCKTAKE, event=EventFactory(), author=UserFactory()
    )

    # Authentication (2), the items with their quantities, the latest stocktake,
    # the latest operations with their event and member, their movements; the
    # orders with their event, their lines and their delivery.
    with django_assert_max_num_queries(9):
        board_client.get(STOCK)


# Adding and correcting


def test_a_member_adds_an_item(board_client):
    """
    Given a member of the board
    When they add juice, low below 24, moved by 6, best before 14 February 2027
    Then the item is recorded with nothing in stock, best before February 2027
    """
    response = send(board_client, "post", ITEMS_PATH, payload(best_before="2027-02-14"))

    assert response.status_code == 201
    item = StockItem.objects.get()
    assert response.json() == {
        "id": item.pk,
        "name": "Jus de fruits 1 L",
        "category": "drinks",
        "unit": "",
        "threshold": "24.00",
        "step": "6.00",
        "best_before": "2027-02-01",
    }
    assert quantity_of(item) == 0


@pytest.mark.parametrize(
    ("changes", "error"),
    [
        ({"name": "JUS DE POMME 1 l"}, refusal(None, "Un article porte déjà ce nom.")),
        ({"name": "  "}, refusal("name", "Ce champ ne peut pas être vide.")),
        (
            {"threshold": "-1"},
            refusal("threshold", "Assurez-vous que cette valeur est supérieure ou égale à 0."),
        ),
        ({"step": "0"}, refusal("step", "Indiquez un pas supérieur à zéro.")),
        (
            {"step": "0.125"},
            refusal("step", "Assurez-vous qu’il n’y a pas plus de 2 chiffres après la virgule."),
        ),
        (
            {"unit": "bouteilles de 1 L"},
            refusal(
                "unit",
                "Assurez-vous que cette valeur comporte au plus 10 caractères (actuellement 17).",
            ),
        ),
    ],
)
def test_an_item_out_of_rule_is_refused(board_client, changes, error):
    """
    Given apple juice in stock already
    When a member adds an item named alike, without a name, below a threshold
    of zero, of a step of nothing or too fine, or of a unit too long
    Then it is refused, under the field the member typed
    """
    StockItemFactory(name="Jus de pomme 1 L")

    response = send(board_client, "post", ITEMS_PATH, payload(**changes))

    assert response.status_code == 422
    assert response.json() == error


def test_a_category_is_one_of_the_chips(board_client):
    """
    Given a member of the board
    When they add an item of a category the stock does not have
    Then the schema refuses it, in French
    """
    response = send(board_client, "post", ITEMS_PATH, payload(category="tools"))

    assert response.status_code == 422
    [item] = response.json()["detail"]
    assert item["loc"] == ["body", "payload", "category"]
    assert (
        item["msg"]
        == "Sélectionnez un choix valide. Ce choix ne fait pas partie de ceux disponibles."
    )


def test_a_member_corrects_an_item_whose_movements_stay(board_client):
    """
    Given 18 litres of juice in stock
    When a member corrects its name, its threshold and its best-before month
    Then the item is rewritten, and its quantity stays
    """
    juice = StockItemFactory(name="Jus 1 L")
    put_in_stock(juice, 18)

    response = send(
        board_client,
        "put",
        url(juice.pk),
        payload(threshold="30", unit="L", best_before="2027-03-31"),
    )

    assert response.status_code == 200
    assert response.json() == {
        "id": juice.pk,
        "name": "Jus de fruits 1 L",
        "category": "drinks",
        "unit": "L",
        "threshold": "30.00",
        "step": "6.00",
        "best_before": "2027-03-01",
    }
    assert quantity_of(juice) == 18


def test_an_item_keeps_its_own_name(board_client):
    """
    Given juice in stock
    When a member corrects it, keeping its name
    Then its own name is not taken for another's
    """
    juice = StockItemFactory(name="Jus de fruits 1 L")

    response = send(board_client, "put", url(juice.pk), payload(category="food"))

    assert response.status_code == 200


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("put", url(999), payload()),
        ("delete", url(999), None),
        ("post", f"{url(999)}/adjustments", {"direction": "in"}),
    ],
)
def test_an_unknown_item_is_not_found(board_client, method, path, body):
    """
    Given no item of that id
    When a member corrects it, deletes it, or adjusts it
    Then the API answers with a 404
    """
    response = send(board_client, method, path, body)

    assert response.status_code == 404
    assert response.json() == {"detail": "Introuvable."}


# Deleting


def test_a_member_deletes_an_item_never_moved(board_client):
    """
    Given juice added by mistake, never moved
    When a member deletes it
    Then it leaves the stock
    """
    juice = StockItemFactory()

    response = board_client.delete(url(juice.pk))

    assert response.status_code == 204
    assert not StockItem.objects.exists()


def test_an_item_that_has_moved_cannot_be_deleted(board_client):
    """
    Given coffee bought once
    When a member deletes it
    Then it is refused: its movements keep it in the history, and a threshold
    of zero is offered instead
    """
    coffee = StockItemFactory(name="Café moulu 1 kg")
    put_in_stock(coffee, 4)

    response = board_client.delete(url(coffee.pk))

    assert response.status_code == 422
    assert response.json() == refusal(
        None,
        "Impossible de supprimer « Café moulu 1 kg » : ses mouvements ou ses commandes le "
        "gardent dans l’historique. Mettez plutôt son seuil à 0, il ne sera plus signalé bas.",
    )
    assert StockItem.objects.exists()


# Adjusting


def test_plus_adds_a_step_recorded_with_the_member(board_client, board_member):
    """
    Given 144 cans in stock, moved by 24
    When a member clicks on plus
    Then 24 cans come in, by an adjustment of the member, and the item tells
    its new quantity
    """
    cans = StockItemFactory()
    put_in_stock(cans, 144)

    response = adjust(board_client, cans, "in")

    assert response.status_code == 200
    body = response.json()
    assert (body["item"]["id"], body["quantity"], body["low"], body["level"]) == (
        cans.pk,
        "168.00",
        False,
        100,
    )
    operation = StockOperation.objects.get(reason=StockOperationReason.ADJUSTMENT)
    assert (operation.author, operation.label, operation.event) == (board_member, "", None)
    assert [(movement.item, movement.delta) for movement in operation.movements.all()] == [
        (cans, Decimal(24))
    ]


def test_minus_takes_a_step_out(board_client):
    """
    Given 144 cans in stock, moved by 24
    When a member clicks on minus
    Then 24 cans go out
    """
    cans = StockItemFactory()
    put_in_stock(cans, 144)

    response = adjust(board_client, cans, "out")

    assert response.json()["quantity"] == "120.00"
    assert StockMovement.objects.get(operation__reason=StockOperationReason.ADJUSTMENT).delta == -24


def test_minus_takes_what_is_left_when_less_than_a_step_is(board_client):
    """
    Given half a kilogram of sweets left, moved by the kilogram
    When a member clicks on minus
    Then the half kilogram goes out: the stock never goes below zero
    """
    sweets = StockItemFactory(step=Decimal(1), threshold=Decimal(3))
    put_in_stock(sweets, "0.5")

    response = adjust(board_client, sweets, "out")

    assert (response.json()["quantity"], response.json()["level"]) == ("0.00", 0)


def test_minus_is_refused_when_nothing_is_left(board_client):
    """
    Given cans all gone, their second click sent at once with the first
    When a member clicks on minus
    Then it is refused, and nothing is recorded
    """
    cans = StockItemFactory()

    response = adjust(board_client, cans, "out")

    assert response.status_code == 422
    assert response.json() == refusal(None, "Il n’en reste plus en stock.")
    assert not StockOperation.objects.exists()


def test_a_direction_is_in_or_out(board_client):
    """
    Given cans in stock
    When a click comes without a direction the stock knows
    Then the schema refuses it
    """
    response = adjust(board_client, StockItemFactory(), "up")

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "payload", "direction"]


def test_adjusting_locks_the_item_first(board_client):
    """
    Given cans in stock
    When a member clicks on minus
    Then the item is locked before its quantity is read: two clicks at once
    never take more than is left
    """
    cans = StockItemFactory()
    put_in_stock(cans, 48)

    with CaptureQueriesContext(connection) as queries:
        adjust(board_client, cans, "out")

    statements = [query["sql"] for query in queries.captured_queries]
    [lock] = [index for index, sql in enumerate(statements) if "FOR UPDATE" in sql]
    summing = next(index for index, sql in enumerate(statements) if "SUM(" in sql)
    assert StockItem._meta.db_table in statements[lock]
    assert lock < summing


# The shopping list


def test_the_shopping_list_of_the_mockup_brings_each_low_item_back_to_its_threshold(
    board_client,
):
    """
    Given the fourteen items of the mockup
    When a member reads the stock
    Then the shopping list buys 6 litres of juice, 1,5 kg of sweets and 2 bags
    of fries, in the stock's order; the kegs at their threshold are not on it
    """
    items = build_mockup()

    shopping = board_client.get(STOCK).json()["shopping_list"]

    assert shopping == [
        {
            "item": {"id": items["Jus de fruits 1 L"].pk, "name": "Jus de fruits 1 L", "unit": ""},
            "quantity": "6.00",
        },
        {
            "item": {"id": items["Bonbons assortis"].pk, "name": "Bonbons assortis", "unit": "kg"},
            "quantity": "1.50",
        },
        {
            "item": {
                "id": items["Frites surgelées 2,5 kg"].pk,
                "name": "Frites surgelées 2,5 kg",
                "unit": "",
            },
            "quantity": "2.00",
        },
    ]


@pytest.mark.parametrize(
    ("held", "to_buy"),
    [("0", "24.00"), ("12", "12.00"), ("13", "12.00"), ("23", "6.00")],
)
def test_the_shopping_list_buys_by_the_step(board_client, held, to_buy):
    """
    Given juice below its threshold of 24, bought by the pack of 6
    When a member reads the stock
    Then what brings it back to 24 is rounded up to a whole pack
    """
    juice = StockItemFactory(threshold=Decimal(24), step=Decimal(6))
    if held != "0":
        put_in_stock(juice, held)

    [line] = board_client.get(STOCK).json()["shopping_list"]

    assert line["quantity"] == to_buy


def test_nothing_to_buy_while_every_item_is_above_its_threshold(board_client):
    """
    Given juice at its threshold, and syrup without one
    When a member reads the stock
    Then the shopping list is empty
    """
    put_in_stock(StockItemFactory(threshold=Decimal(24)), 24)
    StockItemFactory(threshold=Decimal(0))

    assert board_client.get(STOCK).json()["shopping_list"] == []
