"""The stock of the mockup (Stock.dc.html): its fourteen items, each with the
quantity, step, threshold and best-before month it shows. Fictitious, like
every name of the mockup.
"""

import datetime as dt
from decimal import Decimal

from stock.models import StockItemCategory
from tests.stock.factories import StockItemFactory, StockMovementFactory, StockOperationFactory

C = StockItemCategory

# Its name, category, unit, quantity, step, threshold and best-before month.
ITEMS = [
    ("Canettes de soda 33 cl", C.DRINKS, "", "144", "24", "96", dt.date(2027, 5, 1)),
    ("Bouteilles d’eau 50 cl", C.DRINKS, "", "60", "12", "48", dt.date(2027, 6, 1)),
    ("Jus de fruits 1 L", C.DRINKS, "", "18", "6", "24", dt.date(2027, 2, 1)),
    ("Fûts de bière 20 L", C.DRINKS, "fûts", "2", "1", "2", dt.date(2026, 12, 1)),
    ("Café moulu 1 kg", C.DRINKS, "", "4", "1", "3", dt.date(2027, 4, 1)),
    ("Bonbons assortis", C.FOOD, "kg", "1.5", "0.5", "3", dt.date(2027, 3, 1)),
    ("Frites surgelées 2,5 kg", C.FOOD, "", "4", "1", "6", dt.date(2027, 1, 1)),
    ("Sucre en morceaux 1 kg", C.FOOD, "", "5", "1", "2", None),
    ("Gobelets réutilisables", C.SUPPLIES, "", "412", "10", "300", None),
    ("Gobelets carton", C.SUPPLIES, "", "250", "50", "200", None),
    ("Barquettes à frites", C.SUPPLIES, "", "380", "50", "300", None),
    ("Serviettes (paquets de 100)", C.SUPPLIES, "", "6", "1", "4", None),
    ("Cartons de loto", C.LOTTO_RAFFLE, "", "1200", "100", "600", None),
    ("Carnets de tombola", C.LOTTO_RAFFLE, "", "14", "1", "10", None),
]

# Below their threshold: the juice (18 < 24), the sweets (1,5 < 3) and the
# fries (4 < 6). The kegs (2 = 2) are not.
LOW = ["Jus de fruits 1 L", "Bonbons assortis", "Frites surgelées 2,5 kg"]

# How full each bar is, rounded as the mockup does (Math.round). Full at the
# threshold, not at twice it as the mockup draws it (A19, 20/10/2026): only the
# low items are not.
LEVELS = {
    "Canettes de soda 33 cl": 100,
    "Bouteilles d’eau 50 cl": 100,
    "Jus de fruits 1 L": 75,
    "Fûts de bière 20 L": 100,
    "Café moulu 1 kg": 100,
    "Bonbons assortis": 50,
    "Frites surgelées 2,5 kg": 67,
    "Sucre en morceaux 1 kg": 100,
    "Gobelets réutilisables": 100,
    "Gobelets carton": 100,
    "Barquettes à frites": 100,
    "Serviettes (paquets de 100)": 100,
    "Cartons de loto": 100,
    "Carnets de tombola": 100,
}


def build_mockup():
    """The mockup's items, by name, their quantities put in stock by a single
    purchase.
    """
    purchase = StockOperationFactory()
    items = {}
    for name, category, unit, quantity, step, threshold, best_before in ITEMS:
        items[name] = StockItemFactory(
            name=name,
            category=category,
            unit=unit,
            step=Decimal(step),
            threshold=Decimal(threshold),
            best_before=best_before,
        )
        StockMovementFactory(operation=purchase, item=items[name], delta=Decimal(quantity))
    return items
