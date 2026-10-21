"""The reference scenario of phase 11 (D16), which the management control and
the report of the general meeting both tell, and how its operations are placed
in time.
"""

import datetime as dt
from decimal import Decimal
from zoneinfo import ZoneInfo

from stock.models import StockItemCategory, StockOperation, StockOperationReason
from tests.events.factories import EventFactory
from tests.stock.factories import StockItemFactory, bought, moved
from tests.treasury.factories import IncomeFactory, LedgerEntryFactory

PARIS = ZoneInfo("Europe/Paris")


def recorded(movement, moment, event=None):
    """Place the operation of a movement at a moment, and at an event."""
    StockOperation.objects.filter(pk=movement.operation_id).update(created_at=moment, event=event)
    return movement.operation


def reference_scenario():
    """At the brocante of 13 September 2026: the shopping of the bar, 50,00 €,
    puts 48 cans in stock for 26,40 €; 24 more are bought for 14,40 €, no
    expense paying them; the bar consumes 30 and takes 60,00 €; a stocktake of
    no event finds 40.
    """
    brocante = EventFactory(title="Brocante", starts_at=dt.datetime(2026, 9, 13, 7, tzinfo=PARIS))
    cans = StockItemFactory(name="Canettes de soda 33 cl", category=StockItemCategory.DRINKS)
    shopping = LedgerEntryFactory(
        label="Courses buvette", amount=Decimal("50.00"), event=brocante, date=dt.date(2026, 9, 12)
    )
    shopping.stock_purchase = recorded(
        bought(cans, 48, "26.40"), dt.datetime(2026, 9, 12, 10, tzinfo=PARIS), brocante
    )
    shopping.save()
    recorded(bought(cans, 24, "14.40"), dt.datetime(2026, 9, 12, 11, tzinfo=PARIS))
    recorded(
        moved(cans, -30, StockOperationReason.CONSUMPTION),
        dt.datetime(2026, 9, 13, 18, tzinfo=PARIS),
        brocante,
    )
    recorded(
        moved(cans, -2, StockOperationReason.STOCKTAKE), dt.datetime(2026, 9, 20, 10, tzinfo=PARIS)
    )
    IncomeFactory(amount=Decimal("60.00"), event=brocante, date=dt.date(2026, 9, 13))
    return brocante, cans
