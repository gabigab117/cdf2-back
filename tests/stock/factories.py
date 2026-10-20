from decimal import Decimal

import factory

from stock.models import (
    StockItem,
    StockItemCategory,
    StockMovement,
    StockOperation,
    StockOperationReason,
)


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


def put_in_stock(item, quantity):
    """Put some of an item in stock, by an operation of its own."""
    return StockMovementFactory(item=item, delta=Decimal(quantity))
