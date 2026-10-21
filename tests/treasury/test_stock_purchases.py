"""The stock purchase an expense paid (D16): « Mettre en stock », « Achat déjà
saisi », « Retirer », and what they keep the treasury and the stock from doing.
"""

from decimal import Decimal

import pytest
from django.db import IntegrityError, connection
from django.test.utils import CaptureQueriesContext

from stock.models import StockItem, StockMovement, StockOperation, StockOperationReason
from tests.events.factories import EventFactory
from tests.helpers import errors_of, iso, messages_by_place, send
from tests.stock.factories import (
    StockItemFactory,
    StockMovementFactory,
    StockOperationFactory,
    moved,
)
from tests.stock.test_orders import order_url, received, sweets_and_juice
from tests.treasury.factories import IncomeFactory, LedgerEntryFactory
from tests.treasury.test_entries import correct
from treasury.models import LedgerEntry

pytestmark = pytest.mark.django_db

TREASURY = "/api/board/treasury"


def stock_purchase_url(entry):
    return f"{TREASURY}/entries/{entry.pk}/stock-purchase"


def lines(*rows):
    """The lines of a purchase put in stock: its rows are (item, quantity, cost)."""
    return {
        "lines": [
            {"item": item.pk, "quantity": str(quantity), "cost": str(cost)}
            for item, quantity, cost in rows
        ]
    }


def costs(operation, *rows):
    """An existing purchase and the cost of each line: its rows are (item, cost)."""
    return {
        "operation": operation.pk,
        "lines": [{"item": item.pk, "cost": str(cost)} for item, cost in rows],
    }


def shopping_of_the_bar():
    """The shopping of the bar for the brocante, 50,00 €, paid with the card."""
    brocante = EventFactory(title="Brocante")
    return LedgerEntryFactory(label="Courses buvette", amount=Decimal("50.00"), event=brocante)


def recorded_by_a_volunteer(*rows):
    """A purchase a volunteer recorded in the stock, without its costs: its
    rows are (item, quantity).
    """
    purchase = StockOperationFactory(label="Courses du vendredi")
    for item, quantity in rows:
        StockMovementFactory(operation=purchase, item=item, delta=Decimal(quantity))
    return purchase


# « Mettre en stock »


def test_an_expense_puts_its_purchase_in_stock(board_client, board_member):
    """
    Given the shopping of the bar for the brocante, 50,00 €
    When a member puts in stock what it paid: 48 cans for 26,40 €
    Then a purchase of the member comes into the stock, with the label and the
    event of the expense, the cans at their cost; the expense pays it, 26,40 €
    of it gone into stock, 23,60 € left as a direct charge
    """
    expense = shopping_of_the_bar()
    cans = StockItemFactory()

    response = send(board_client, "post", stock_purchase_url(expense), lines((cans, 48, "26.40")))

    assert response.status_code == 200
    purchase = StockOperation.objects.get()
    assert (purchase.reason, purchase.label, purchase.event, purchase.author) == (
        StockOperationReason.PURCHASE,
        "Courses buvette",
        expense.event,
        board_member,
    )
    assert StockMovement.objects.get().cost == Decimal("26.40")
    body = response.json()
    assert body["stock_purchase"] == {
        "id": purchase.pk,
        "reason": "purchase",
        "label": "Courses buvette",
        "created_at": iso(purchase.created_at),
    }
    assert (body["stocked_cost"], body["unstocked_cost"]) == ("26.40", "23.60")


def test_the_costs_put_in_stock_never_add_up_to_more_than_the_expense(board_client):
    """
    Given the shopping of the bar, 50,00 €
    When a member puts in stock cans for 30,00 € and water for 25,00 €
    Then it is refused, and nothing comes into the stock
    """
    expense = shopping_of_the_bar()
    cans, water = StockItemFactory(), StockItemFactory()

    response = send(
        board_client,
        "post",
        stock_purchase_url(expense),
        lines((cans, 48, "30.00"), (water, 24, "25.00")),
    )

    assert messages_by_place(response) == {
        ("body",): "Les prix des articles dépassent le montant de la dépense."
    }
    assert not StockOperation.objects.exists()


def test_the_lines_put_in_stock_are_checked_as_a_purchase(board_client):
    """
    Given the shopping of the bar
    When a member puts in stock an item that does not exist, and cans without
    their cost
    Then each is refused under its line
    """
    expense = shopping_of_the_bar()
    body = lines((StockItemFactory(), 48, "26.40"))
    body["lines"].append({"item": 999, "quantity": "1", "cost": "1.00"})
    del body["lines"][0]["cost"]

    response = send(board_client, "post", stock_purchase_url(expense), body)

    assert messages_by_place(response) == {
        ("body", "payload", "lines", 0, "cost"): "Ce champ est obligatoire."
    }
    body["lines"][0]["cost"] = "26.40"
    response = send(board_client, "post", stock_purchase_url(expense), body)
    assert messages_by_place(response) == {
        ("body", "lines", 1, "item"): "Choisissez un article existant."
    }


def test_an_income_puts_nothing_in_stock(board_client):
    """
    Given the takings of the bar
    When a member puts in stock what they paid
    Then it is refused: only an expense pays a purchase of the stock
    """
    takings = IncomeFactory()

    response = send(
        board_client, "post", stock_purchase_url(takings), lines((StockItemFactory(), 1, "1.00"))
    )

    assert messages_by_place(response) == {("body",): "Seule une dépense paie un achat du stock."}


def test_an_expense_pays_a_single_purchase(board_client):
    """
    Given the shopping of the bar, which put its cans in stock already
    When a member puts in stock its water too
    Then it is refused: an expense pays a single purchase of the stock
    """
    expense = shopping_of_the_bar()
    send(
        board_client, "post", stock_purchase_url(expense), lines((StockItemFactory(), 48, "26.40"))
    )

    response = send(
        board_client, "post", stock_purchase_url(expense), lines((StockItemFactory(), 24, "6.00"))
    )

    assert messages_by_place(response) == {
        ("body",): "Cette dépense paie déjà un autre achat du stock."
    }


def test_putting_in_stock_locks_the_expense_then_the_items(board_client):
    """
    Given the shopping of the bar
    When a member puts its cans in stock
    Then the expense is locked first, then the items, as every write of the
    stock locks them
    """
    expense = shopping_of_the_bar()
    cans = StockItemFactory()

    with CaptureQueriesContext(connection) as queries:
        send(board_client, "post", stock_purchase_url(expense), lines((cans, 48, "26.40")))

    locks = [query["sql"] for query in queries.captured_queries if "FOR UPDATE" in query["sql"]]
    assert LedgerEntry._meta.db_table in locks[0]
    assert StockItem._meta.db_table in locks[1]


# « Achat déjà saisi »


def test_an_expense_pays_a_purchase_a_volunteer_recorded(board_client):
    """
    Given cans and water a volunteer bought and recorded in the stock without
    their costs, and the shopping of the bar, 50,00 €, that paid them
    When a member links them, the cans at 26,40 €, the water at 6,00 €
    Then the purchase keeps its costs, waits for none, and the expense pays it
    """
    cans, water = StockItemFactory(), StockItemFactory()
    purchase = recorded_by_a_volunteer((cans, 48), (water, 24))
    expense = shopping_of_the_bar()

    response = send(
        board_client,
        "put",
        stock_purchase_url(expense),
        costs(purchase, (cans, "26.40"), (water, "6.00")),
    )

    assert response.status_code == 200
    assert (response.json()["stocked_cost"], response.json()["unstocked_cost"]) == (
        "32.40",
        "17.60",
    )
    assert dict(StockMovement.objects.values_list("item", "cost")) == {
        cans.pk: Decimal("26.40"),
        water.pk: Decimal("6.00"),
    }
    expense.refresh_from_db()
    assert expense.stock_purchase == purchase


def test_the_purchase_of_an_expense_is_corrected_from_it(board_client):
    """
    Given the shopping of the bar, which pays the volunteer's cans at 26,40 €
    When a member gives them again from the expense, at 28,80 €
    Then the cans cost 28,80 €
    """
    cans = StockItemFactory()
    purchase = recorded_by_a_volunteer((cans, 48))
    expense = shopping_of_the_bar()
    send(board_client, "put", stock_purchase_url(expense), costs(purchase, (cans, "26.40")))

    send(board_client, "put", stock_purchase_url(expense), costs(purchase, (cans, "28.80")))

    assert StockMovement.objects.get().cost == Decimal("28.80")


@pytest.mark.parametrize(
    ("make", "place", "message"),
    [
        (
            lambda cans: 999,
            ("body", "operation"),
            "Choisissez un achat ou une réception du stock.",
        ),
        (
            lambda cans: moved(cans, -6, StockOperationReason.CONSUMPTION).operation_id,
            ("body",),
            "Seuls un achat et une réception ont des prix.",
        ),
    ],
)
def test_only_a_purchase_or_a_delivery_is_paid_by_an_expense(board_client, make, place, message):
    """
    Given the shopping of the bar
    When a member links an operation that does not exist, or a consumption
    Then it is refused
    """
    cans = StockItemFactory()
    expense = shopping_of_the_bar()

    response = send(
        board_client,
        "put",
        stock_purchase_url(expense),
        {"operation": make(cans), "lines": [{"item": cans.pk, "cost": "1.00"}]},
    )

    assert messages_by_place(response) == {place: message}


def test_a_purchase_is_paid_by_a_single_expense(board_client):
    """
    Given the volunteer's cans, which the shopping of the bar pays
    When a member links them to another expense
    Then it is refused
    """
    cans = StockItemFactory()
    purchase = recorded_by_a_volunteer((cans, 48))
    send(
        board_client,
        "put",
        stock_purchase_url(shopping_of_the_bar()),
        costs(purchase, (cans, "26.40")),
    )

    response = send(
        board_client,
        "put",
        stock_purchase_url(LedgerEntryFactory()),
        costs(purchase, (cans, "1.00")),
    )

    assert messages_by_place(response) == {
        ("body", "operation"): "Cet achat est déjà payé par une autre dépense."
    }


def test_the_costs_linked_never_add_up_to_more_than_the_expense(board_client):
    """
    Given the volunteer's cans, and the shopping of the bar, 50,00 €
    When a member links them at 60,00 €
    Then it is refused, and the cans keep no cost
    """
    cans = StockItemFactory()
    purchase = recorded_by_a_volunteer((cans, 48))

    response = send(
        board_client,
        "put",
        stock_purchase_url(shopping_of_the_bar()),
        costs(purchase, (cans, "60.00")),
    )

    assert messages_by_place(response) == {
        ("body",): "Les prix des articles dépassent le montant de la dépense."
    }
    assert StockMovement.objects.get().cost is None


def test_linking_locks_the_purchase_then_the_expense(board_client):
    """
    Given the volunteer's cans, and the shopping of the bar
    When a member links them
    Then the purchase is locked first, then the expense: the order every write
    of the stock and the treasury keeps
    """
    cans = StockItemFactory()
    purchase = recorded_by_a_volunteer((cans, 48))
    expense = shopping_of_the_bar()

    with CaptureQueriesContext(connection) as queries:
        send(board_client, "put", stock_purchase_url(expense), costs(purchase, (cans, "26.40")))

    locks = [query["sql"] for query in queries.captured_queries if "FOR UPDATE" in query["sql"]]
    assert f'FROM "{StockOperation._meta.db_table}"' in locks[0]
    assert LedgerEntry._meta.db_table in locks[1]


# « Retirer », and the purchases to choose from


def test_an_expense_pays_its_purchase_no_more(board_client):
    """
    Given the shopping of the bar, which pays the volunteer's cans
    When a member unlinks them
    Then the expense pays no purchase, and the cans stay in the stock, at their cost
    """
    cans = StockItemFactory()
    purchase = recorded_by_a_volunteer((cans, 48))
    expense = shopping_of_the_bar()
    send(board_client, "put", stock_purchase_url(expense), costs(purchase, (cans, "26.40")))

    response = send(board_client, "delete", stock_purchase_url(expense))

    assert (response.json()["stock_purchase"], response.json()["stocked_cost"]) == (None, None)
    assert StockMovement.objects.get().cost == Decimal("26.40")


def test_the_purchases_to_choose_from_are_those_no_expense_paid(board_client):
    """
    Given the volunteer's purchase, a delivery, a purchase the shopping of the
    bar pays, and a consumption
    When a member lists the purchases to link
    Then the delivery and the volunteer's purchase come, the latest first
    """
    cans = StockItemFactory()
    volunteer = recorded_by_a_volunteer((cans, 48))
    delivery = moved(cans, 24, StockOperationReason.DELIVERY).operation
    paid = recorded_by_a_volunteer((cans, 24))
    send(
        board_client, "put", stock_purchase_url(shopping_of_the_bar()), costs(paid, (cans, "13.20"))
    )
    moved(cans, -6, StockOperationReason.CONSUMPTION)

    body = board_client.get(f"{TREASURY}/stock-purchases").json()

    assert [operation["id"] for operation in body["items"]] == [delivery.pk, volunteer.pk]


# What the link keeps the treasury and the stock from doing


def test_an_expense_never_costs_less_than_its_stock_purchase(board_client):
    """
    Given the shopping of the bar, 50,00 €, which put 26,40 € of cans in stock
    When a member corrects its amount to 20,00 €
    Then it is refused under the amount
    """
    expense = shopping_of_the_bar()
    send(
        board_client, "post", stock_purchase_url(expense), lines((StockItemFactory(), 48, "26.40"))
    )

    response = correct(board_client, expense, amount="20.00")

    assert messages_by_place(response) == {
        ("body", "amount"): (
            "Le montant ne peut pas être plus petit que les prix des articles mis en stock."
        )
    }


def test_an_amount_below_the_stock_purchase_is_refused_with_the_other_errors(board_client):
    """
    Given the shopping of the bar, 50,00 €, which put 26,40 € of cans in stock
    When a member corrects it without a label for 20,00 €, then for nothing
    Then the label and the amount are refused at once, and an amount of
    nothing is refused as on any line
    """
    expense = shopping_of_the_bar()
    send(
        board_client, "post", stock_purchase_url(expense), lines((StockItemFactory(), 48, "26.40"))
    )

    below = correct(board_client, expense, label="", amount="20.00")
    nothing = correct(board_client, expense, amount="0.00")

    assert messages_by_place(below) == {
        ("body", "label"): "Ce champ ne peut pas être vide.",
        ("body", "amount"): (
            "Le montant ne peut pas être plus petit que les prix des articles mis en stock."
        ),
    }
    assert messages_by_place(nothing) == {
        ("body", "amount"): "Indiquez un montant supérieur à zéro."
    }


def test_an_expense_that_paid_a_purchase_stays_an_expense():
    """
    Given an expense that paid a purchase of the stock
    When it is turned into an income, checked, then written
    Then it is refused under its kind, and the database refuses it too
    """
    expense = LedgerEntryFactory(stock_purchase=StockOperationFactory())
    expense.kind = "income"
    expense.category = "bar"

    assert errors_of(expense) == {"kind": ["Seule une dépense paie un achat du stock."]}
    with pytest.raises(IntegrityError):
        expense.save()


def test_the_costs_of_a_purchase_an_expense_paid_are_corrected_from_it(board_client):
    """
    Given the volunteer's cans, which the shopping of the bar pays
    When a member writes their costs from the stock
    Then it is refused: they are corrected from the expense
    """
    cans = StockItemFactory()
    purchase = recorded_by_a_volunteer((cans, 48))
    send(
        board_client,
        "put",
        stock_purchase_url(shopping_of_the_bar()),
        costs(purchase, (cans, "26.40")),
    )

    response = send(
        board_client,
        "put",
        f"/api/board/stock/operations/{purchase.pk}/costs",
        {"lines": [{"item": cans.pk, "cost": "1.00"}]},
    )

    assert messages_by_place(response) == {
        ("body",): "Cet achat est payé par une dépense : ses prix se corrigent depuis elle."
    }


def test_an_operation_tells_the_expense_that_paid_it(board_client):
    """
    Given the volunteer's cans, which the shopping of the bar pays
    When a member reads the purchase
    Then it names the expense, its amount and its date
    """
    cans = StockItemFactory()
    purchase = recorded_by_a_volunteer((cans, 48))
    expense = shopping_of_the_bar()
    send(board_client, "put", stock_purchase_url(expense), costs(purchase, (cans, "26.40")))

    body = board_client.get(f"/api/board/stock/operations/{purchase.pk}").json()

    assert body["expense"] == {
        "id": expense.pk,
        "label": "Courses buvette",
        "amount": "50.00",
        "date": expense.date.isoformat(),
    }


def test_a_delivery_an_expense_paid_is_not_cancelled(board_client):
    """
    Given the order of sweets and juice, received today, its delivery paid by
    the invoice's expense
    When a member cancels the delivery
    Then it is refused: the expense lets it go first
    """
    document, _sweets, _juice = sweets_and_juice()
    delivery = received(document)
    LedgerEntryFactory(amount=Decimal("500.00"), stock_purchase=delivery)

    response = send(board_client, "delete", order_url(document.pk, "/delivery"))

    assert messages_by_place(response) == {
        ("body",): "Cette réception est payée par une dépense : retirez d’abord ce rattachement."
    }
