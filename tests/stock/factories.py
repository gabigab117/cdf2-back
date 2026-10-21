from decimal import Decimal

import factory

from documents.models import DocumentCategory
from stock.models import (
    OrderLine,
    StockItem,
    StockItemCategory,
    StockMovement,
    StockOperation,
    StockOperationReason,
)
from tests.documents.factories import DocumentFactory


class StockItemFactory(factory.django.DjangoModelFactory):
    """Cans of soda, bought by the pack of 24, low below 96."""

    class Meta:
        model = StockItem

    name = factory.Sequence(lambda n: f"Canettes de soda 33 cl ({n})")
    category = StockItemCategory.DRINKS
    threshold = Decimal(96)
    step = Decimal(24)


class StockOperationFactory(factory.django.DjangoModelFactory):
    """A purchase recorded without a member, as a deleted account leaves it."""

    class Meta:
        model = StockOperation

    reason = StockOperationReason.PURCHASE


class StockMovementFactory(factory.django.DjangoModelFactory):
    """A pack of 24 coming in."""

    class Meta:
        model = StockMovement

    operation = factory.SubFactory(StockOperationFactory)
    item = factory.SubFactory(StockItemFactory)
    delta = Decimal(24)


def order_document(**fields):
    """The order of sweets for Halloween, validated, to be delivered on 27 October."""
    return DocumentFactory(
        **{
            "category": DocumentCategory.ORDER,
            "title": "Bon de commande — Bonbons et goûter",
            "issuer": "Confiserie du Nord",
            "extracted": {"delivery_date": "2026-10-27", "items": ""},
            "validated": True,
        }
        | fields
    )


class OrderLineFactory(factory.django.DjangoModelFactory):
    """Twelve of an item an order brings."""

    class Meta:
        model = OrderLine

    document = factory.LazyFunction(order_document)
    item = factory.SubFactory(StockItemFactory)
    quantity = Decimal(12)


def put_in_stock(item, quantity):
    """Put some of an item in stock, by an operation of its own."""
    return StockMovementFactory(item=item, delta=Decimal(quantity))


def bought(item, quantity, cost):
    """A purchase of an item, by an operation of its own, at what its line cost."""
    return StockMovementFactory(item=item, delta=Decimal(quantity), cost=Decimal(cost))


def moved(item, delta, reason):
    """A movement of an item, by an operation of its own, for a reason."""
    return StockMovementFactory(item=item, delta=Decimal(delta), operation__reason=reason)


def quantity_of(item):
    """What the stock holds of an item: the sum of its movements."""
    return sum(movement.delta for movement in StockMovement.objects.filter(item=item))
