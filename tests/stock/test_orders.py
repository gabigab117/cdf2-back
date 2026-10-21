import datetime as dt
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from documents.models import Document, DocumentCategory
from documents.schemas import EMPTY_EXTRACTED
from stock.models import OrderLine, StockItem, StockOperation, StockOperationReason
from tests.documents.factories import DocumentFactory
from tests.events.factories import EventFactory
from tests.helpers import ahead, iso, member_json, messages_by_place, send
from tests.stock.factories import (
    OrderLineFactory,
    StockItemFactory,
    StockOperationFactory,
    order_document,
    put_in_stock,
    quantity_of,
)

pytestmark = pytest.mark.django_db

STOCK = "/api/board/stock"


def order_url(document_id, part=""):
    return f"{STOCK}/orders/{document_id}{part}"


def lines(*rows):
    """The lines of an order as its form sends them: its rows are (item, quantity)."""
    return {"lines": [{"item": item.pk, "quantity": str(quantity)} for item, quantity in rows]}


def refusal(message):
    return {"detail": [{"type": "validation_error", "loc": ["body"], "msg": message}]}


def received(document, member=None):
    """The delivery of an order, as « Réceptionner la livraison » records it."""
    delivery = StockOperationFactory(
        reason=StockOperationReason.DELIVERY, label=document.title, document=document, author=member
    )
    for line in document.order_lines.all():
        delivery.movements.create(item=line.item, delta=line.quantity)
    return delivery


def sweets_and_juice():
    """The order of sweets for Halloween: 12 kg of sweets and 60 litres of juice."""
    halloween = EventFactory(title="Halloween des enfants")
    document = order_document(event=halloween)
    sweets = StockItemFactory(name="Bonbons assortis", unit="kg")
    juice = StockItemFactory(name="Jus de fruits 1 L")
    OrderLineFactory(document=document, item=sweets, quantity=Decimal(12))
    OrderLineFactory(document=document, item=juice, quantity=Decimal(60))
    return document, sweets, juice


# Reading


def test_an_order_tells_its_lines_and_its_delivery(board_client):
    """
    Given the order of sweets for Halloween, from the Confiserie du Nord, to be
    delivered on 27 October, of 12 kg of sweets and 60 litres of juice
    When a member reads it
    Then it comes with its lines, in the order they were written, not received
    """
    document, sweets, juice = sweets_and_juice()

    response = board_client.get(order_url(document.pk))

    assert response.status_code == 200
    assert response.json() == {
        "id": document.pk,
        "title": "Bon de commande — Bonbons et goûter",
        "issuer": "Confiserie du Nord",
        "delivery_date": "2026-10-27",
        "event": {"id": document.event_id, "title": "Halloween des enfants"},
        "validated": True,
        "lines": [
            {
                "item": {"id": sweets.pk, "name": "Bonbons assortis", "unit": "kg"},
                "quantity": "12.00",
            },
            {
                "item": {"id": juice.pk, "name": "Jus de fruits 1 L", "unit": ""},
                "quantity": "60.00",
            },
        ],
        "delivery": None,
        "undoable": False,
    }


@pytest.mark.parametrize(
    ("method", "part", "body"),
    [
        ("get", "", None),
        ("put", "/lines", {"lines": []}),
        ("post", "/delivery", None),
        ("delete", "/delivery", None),
    ],
)
def test_a_document_that_is_no_order_is_not_found(board_client, method, part, body):
    """
    Given an invoice, and no document of the id 999
    When a member reads, writes, receives or cancels them as orders
    Then the API answers with a 404
    """
    invoice = DocumentFactory(category=DocumentCategory.INVOICE)

    for document_id in (invoice.pk, 999):
        response = send(board_client, method, order_url(document_id, part), body)

        assert response.status_code == 404
        assert response.json() == {"detail": "Introuvable."}


# Lines


def test_a_member_writes_the_lines_of_an_order(board_client):
    """
    Given the order of sweets and juice
    When a member rewrites its lines: 10 kg of sweets and 500 paper cups
    Then the order holds those two lines alone
    """
    document, sweets, _juice = sweets_and_juice()
    cups = StockItemFactory(name="Gobelets carton")

    response = send(
        board_client, "put", order_url(document.pk, "/lines"), lines((sweets, 10), (cups, 500))
    )

    assert response.status_code == 200
    assert [(line["item"]["name"], line["quantity"]) for line in response.json()["lines"]] == [
        ("Bonbons assortis", "10.00"),
        ("Gobelets carton", "500.00"),
    ]
    assert list(OrderLine.objects.filter(document=document).values_list("item", "quantity")) == [
        (sweets.pk, Decimal(10)),
        (cups.pk, Decimal(500)),
    ]


def test_an_order_may_lose_all_its_lines(board_client):
    """
    Given the order of sweets and juice, which will never come
    When a member removes all its lines
    Then the order brings nothing to the stock, and the Stock page leaves it
    """
    document, _sweets, _juice = sweets_and_juice()

    response = send(board_client, "put", order_url(document.pk, "/lines"), {"lines": []})

    assert response.json()["lines"] == []
    assert board_client.get(STOCK).json()["orders"] == []


def test_each_line_out_of_rule_is_refused_under_its_position(board_client):
    """
    Given the order of sweets and juice
    When its lines name the sweets twice, nothing of the juice, an item finer
    than the hundredth, and an item that does not exist
    Then each line is refused under its own position, and the lines stay
    """
    document, sweets, juice = sweets_and_juice()
    cups = StockItemFactory()
    body = lines((sweets, 2), (juice, 0), (sweets, 1), (cups, "0.125"))
    body["lines"].append({"item": 999, "quantity": "1"})

    response = send(board_client, "put", order_url(document.pk, "/lines"), body)

    assert messages_by_place(response) == {
        ("body", "lines", 1, "quantity"): "Indiquez une quantité supérieure à zéro.",
        ("body", "lines", 2, "item"): "Cet article figure déjà dans la commande.",
        ("body", "lines", 3, "quantity"): (
            "Assurez-vous qu’il n’y a pas plus de 2 chiffres après la virgule."
        ),
        ("body", "lines", 4, "item"): "Choisissez un article existant.",
    }
    assert OrderLine.objects.filter(document=document).count() == 2


def test_the_lines_of_an_order_received_stay_as_they_are(board_client):
    """
    Given the order of sweets and juice, received
    When a member rewrites its lines
    Then it is refused: the delivery is cancelled first
    """
    document, sweets, _juice = sweets_and_juice()
    received(document)

    response = send(board_client, "put", order_url(document.pk, "/lines"), lines((sweets, 1)))

    assert response.json() == refusal(
        "Cette commande est déjà réceptionnée : annulez d’abord la réception."
    )


def test_writing_the_lines_locks_the_order_first(board_client):
    """
    Given the order of sweets and juice
    When a member rewrites its lines
    Then the order is locked first: a delivery cannot slip in between
    """
    document, sweets, _juice = sweets_and_juice()

    with CaptureQueriesContext(connection) as queries:
        send(board_client, "put", order_url(document.pk, "/lines"), lines((sweets, 3)))

    locks = [query["sql"] for query in queries.captured_queries if "FOR UPDATE" in query["sql"]]
    assert len(locks) == 1
    assert Document._meta.db_table in locks[0]


# Delivery


def test_a_member_receives_a_validated_order(board_client, board_member):
    """
    Given 1,5 kg of sweets in stock, and the validated order of 12 kg of sweets
    and 60 litres of juice for Halloween
    When a member receives the delivery
    Then both come into the stock, by a single delivery of the member, with
    the order and its event, which « Annuler » undoes today
    """
    document, sweets, juice = sweets_and_juice()
    put_in_stock(sweets, "1.5")

    response = send(board_client, "post", order_url(document.pk, "/delivery"))

    assert response.status_code == 200
    delivery = StockOperation.objects.get(reason=StockOperationReason.DELIVERY)
    assert (delivery.label, delivery.event_id, delivery.document, delivery.author) == (
        "Bon de commande — Bonbons et goûter",
        document.event_id,
        document,
        board_member,
    )
    assert (quantity_of(sweets), quantity_of(juice)) == (Decimal("13.5"), Decimal(60))
    body = response.json()
    assert body["delivery"] == {
        "created_at": iso(delivery.created_at),
        "author": member_json(board_member),
    }
    assert body["undoable"] is True


@pytest.mark.parametrize(
    ("state", "message"),
    [
        ("to_review", "Validez d’abord la commande."),
        ("without_lines", "Cette commande n’a aucune ligne de stock."),
        ("received", "Cette commande est déjà réceptionnée."),
    ],
)
def test_an_order_is_received_once_validated_and_with_lines(board_client, state, message):
    """
    Given an order awaiting review, one without any line, and one received
    When a member receives it
    Then it is refused, saying why, and nothing comes into the stock
    """
    document = order_document(validated=state != "to_review")
    if state != "without_lines":
        OrderLineFactory(document=document)
    if state == "received":
        received(document)
    before = StockOperation.objects.count()

    response = send(board_client, "post", order_url(document.pk, "/delivery"))

    assert response.json() == refusal(message)
    assert StockOperation.objects.count() == before


def test_receiving_locks_the_order_then_its_items_by_key(board_client):
    """
    Given the order of sweets and juice
    When a member receives it
    Then the order is locked first, then its items by key: two receptions at
    once bring it in once
    """
    document, _sweets, _juice = sweets_and_juice()

    with CaptureQueriesContext(connection) as queries:
        send(board_client, "post", order_url(document.pk, "/delivery"))

    locks = [query["sql"] for query in queries.captured_queries if "FOR UPDATE" in query["sql"]]
    assert len(locks) == 2
    assert Document._meta.db_table in locks[0]
    assert f'ORDER BY "{StockItem._meta.db_table}"."id" ASC' in locks[1]


# Cancelling the delivery


def test_a_delivery_is_cancelled_the_day_it_was_received(board_client):
    """
    Given the order of sweets and juice, received today
    When a member cancels the delivery
    Then the stock goes back as it was, and the order may be received again
    """
    document, sweets, juice = sweets_and_juice()
    received(document)

    response = send(board_client, "delete", order_url(document.pk, "/delivery"))

    assert response.status_code == 200
    assert (response.json()["delivery"], response.json()["undoable"]) == (None, False)
    assert (quantity_of(sweets), quantity_of(juice)) == (0, 0)
    assert not StockOperation.objects.exists()


def test_a_delivery_is_not_cancelled_the_next_day(board_client, monkeypatch):
    """
    Given the order of sweets and juice, received yesterday
    When a member cancels the delivery
    Then it is refused: a delivery is cancelled the day it was received
    """
    document, _sweets, _juice = sweets_and_juice()
    received(document)
    tomorrow = ahead(1)
    monkeypatch.setattr(timezone, "localdate", lambda *args, **kwargs: tomorrow)

    response = send(board_client, "delete", order_url(document.pk, "/delivery"))

    assert response.json() == refusal("Une réception ne s’annule que le jour même.")


def test_a_delivery_partly_gone_is_not_cancelled(board_client):
    """
    Given the order of sweets and juice, received, and 5 kg of sweets eaten since
    When a member cancels the delivery
    Then it is refused, naming the sweets, and the stock stays
    """
    document, sweets, _juice = sweets_and_juice()
    received(document)
    put_in_stock(sweets, -5)

    response = send(board_client, "delete", order_url(document.pk, "/delivery"))

    assert response.json() == refusal(
        "Le stock a bougé depuis cette réception (« Bonbons assortis ») : elle ne s’annule plus."
    )
    assert quantity_of(sweets) == 7


def test_a_delivery_whose_items_moved_since_is_not_cancelled(board_client):
    """
    Given the order of sweets and juice, received, then 5 kg of sweets eaten and
    5 kg bought back since
    When a member cancels the delivery
    Then it is refused, naming the sweets: the 5 kg eaten came from the delivery,
    and without it the history of the sweets would go below zero
    """
    document, sweets, _juice = sweets_and_juice()
    received(document)
    put_in_stock(sweets, -5)
    put_in_stock(sweets, 5)

    response = send(board_client, "delete", order_url(document.pk, "/delivery"))

    assert response.json() == refusal(
        "Le stock a bougé depuis cette réception (« Bonbons assortis ») : elle ne s’annule plus."
    )
    assert quantity_of(sweets) == 12


def test_a_delivery_followed_by_a_stocktake_is_not_cancelled(board_client):
    """
    Given the order of sweets and juice, received, then a stocktake that found
    no difference
    When a member cancels the delivery
    Then it is refused: the stocktake counted what came
    """
    document, _sweets, _juice = sweets_and_juice()
    received(document)
    StockOperationFactory(reason=StockOperationReason.STOCKTAKE)

    response = send(board_client, "delete", order_url(document.pk, "/delivery"))

    assert response.json() == refusal(
        "Un inventaire a suivi cette réception : elle ne s’annule plus."
    )


def test_cancelling_a_delivery_looks_for_a_later_stocktake_once_its_items_are_locked(
    board_client,
):
    """
    Given the order of sweets and juice, received today
    When a member cancels the delivery
    Then its items are locked before a later stocktake is looked for: a
    stocktake counting them at the same time comes either before, and the
    delivery stays, or after its cancellation
    """
    document, _sweets, _juice = sweets_and_juice()
    received(document)

    with CaptureQueriesContext(connection) as queries:
        send(board_client, "delete", order_url(document.pk, "/delivery"))

    sql = [query["sql"] for query in queries.captured_queries]
    items_locked = next(
        index
        for index, query in enumerate(sql)
        if "FOR UPDATE" in query and f'ORDER BY "{StockItem._meta.db_table}"."id" ASC' in query
    )
    stocktake_sought = next(
        index for index, query in enumerate(sql) if f"'{StockOperationReason.STOCKTAKE}'" in query
    )
    assert items_locked < stocktake_sought


def test_cancelling_a_delivery_locks_the_order_then_the_delivery_then_its_items(board_client):
    """
    Given the order of sweets and juice, received today
    When a member cancels the delivery
    Then the order is locked first, then the delivery, then its items: a
    member writing the costs of the delivery at the same time, who locks it
    too, waits instead of being caught in a deadlock
    """
    document, _sweets, _juice = sweets_and_juice()
    received(document)

    with CaptureQueriesContext(connection) as queries:
        send(board_client, "delete", order_url(document.pk, "/delivery"))

    locks = [query["sql"] for query in queries.captured_queries if "FOR UPDATE" in query["sql"]]
    assert [
        next(
            table
            for table in (Document, StockOperation, StockItem)
            if f'FROM "{table._meta.db_table}"' in sql
        )
        for sql in locks
    ] == [Document, StockOperation, StockItem]


def test_an_order_not_received_has_no_delivery_to_cancel(board_client):
    """
    Given the order of sweets and juice, not received
    When a member cancels its delivery
    Then it is refused: there is none
    """
    document, _sweets, _juice = sweets_and_juice()

    response = send(board_client, "delete", order_url(document.pk, "/delivery"))

    assert response.json() == refusal("Cette commande n’est pas réceptionnée.")


# The Stock page


def test_the_stock_lists_the_orders_to_receive_then_those_received_today(board_client):
    """
    Given validated orders with lines, to be delivered on 27 October, on
    5 November and without date; one received today and one yesterday; one
    validated without lines; one awaiting review with lines; and an invoice
    When a member reads the stock
    Then the three to receive come, the first delivered first, the one without
    date last; then the one received today; the others do not come
    """
    late = order_document(title="Lots du loto", extracted={"delivery_date": "2026-11-05"})
    soon = order_document(title="Bonbons")
    undated = order_document(title="Sapins", extracted={})
    today = order_document(title="Gobelets")
    yesterday = order_document(title="Serviettes")
    for document in (late, soon, undated, today, yesterday):
        OrderLineFactory(document=document)
    order_document(title="Sans ligne")
    OrderLineFactory(document=order_document(title="À vérifier", validated=False))
    DocumentFactory(category=DocumentCategory.INVOICE)
    received(today)
    old = received(yesterday)
    StockOperation.objects.filter(pk=old.pk).update(
        created_at=timezone.now() - dt.timedelta(days=1)
    )

    orders = board_client.get(STOCK).json()["orders"]

    assert [(entry["title"], entry["undoable"]) for entry in orders] == [
        ("Bonbons", False),
        ("Lots du loto", False),
        ("Sapins", False),
        ("Gobelets", True),
    ]


# Documents and items


def test_an_order_with_lines_keeps_its_category(board_client):
    """
    Given the order of sweets and juice, and an order without any line
    When a member corrects each into an invoice
    Then the first is refused under its category, the second becomes an invoice
    """
    document, _sweets, _juice = sweets_and_juice()
    bare = order_document()

    def correct(target):
        return send(
            board_client,
            "put",
            f"/api/board/documents/{target.pk}",
            {
                "category": "invoice",
                "title": target.title,
                "event": None,
                "document_date": None,
                "issuer": "",
                "reference": "",
                "amount": None,
                "due_date": None,
                "paid_on": None,
                "note": "",
                "extracted": EMPTY_EXTRACTED,
            },
        )

    assert messages_by_place(correct(document)) == {
        ("body", "category"): (
            "Cette commande a des lignes de stock : retirez-les avant de changer sa catégorie."
        )
    }
    assert correct(bare).status_code == 200


def test_correcting_an_order_locks_it_before_reading_its_lines(board_client):
    """
    Given the order of sweets and juice
    When a member corrects it into an invoice
    Then the document is locked before its lines are read: lines written at
    the same time cannot slip in between
    """
    document, _sweets, _juice = sweets_and_juice()

    with CaptureQueriesContext(connection) as queries:
        send(
            board_client,
            "put",
            f"/api/board/documents/{document.pk}",
            {
                "category": "invoice",
                "title": document.title,
                "event": None,
                "document_date": None,
                "issuer": "",
                "reference": "",
                "amount": None,
                "due_date": None,
                "paid_on": None,
                "note": "",
                "extracted": EMPTY_EXTRACTED,
            },
        )

    statements = [query["sql"] for query in queries.captured_queries]
    lock = next(index for index, sql in enumerate(statements) if "FOR UPDATE" in sql)
    lines_read = next(
        index for index, sql in enumerate(statements) if OrderLine._meta.db_table in sql
    )
    assert Document._meta.db_table in statements[lock]
    assert lock < lines_read


def test_an_order_deleted_leaves_its_delivery_in_the_stock(board_client):
    """
    Given the order of sweets and juice, received
    When a member deletes the document
    Then its lines go with it, and what came stays in the stock
    """
    document, sweets, _juice = sweets_and_juice()
    delivery = received(document)

    response = board_client.delete(f"/api/board/documents/{document.pk}")

    assert response.status_code == 204
    delivery.refresh_from_db()
    assert delivery.document is None
    assert not OrderLine.objects.exists()
    assert quantity_of(sweets) == 12


def test_an_item_an_order_names_cannot_be_deleted(board_client):
    """
    Given sweets that an order names, never moved
    When a member deletes them
    Then it is refused
    """
    _document, sweets, _juice = sweets_and_juice()

    response = board_client.delete(f"{STOCK}/items/{sweets.pk}")

    assert response.status_code == 422
    assert StockItem.objects.filter(pk=sweets.pk).exists()
