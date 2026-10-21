"""The committee's stock of goods (A19): the drinks, food and supplies of its bar
and its games, counted by their movements. Not the equipment it lends.

An item's quantity is the sum of its movements. Each movement belongs to an
operation, which tells why the stock moved, for which event and who moved it:
a click on minus or plus is an adjustment of a single movement.
"""

from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower

from documents.models import Document
from events.models import EVENT_ERROR_MESSAGES, Event

NO_STEP = "Indiquez un pas supérieur à zéro."
NO_DELTA = "Un mouvement change la quantité."
UNKNOWN_ITEM = "Choisissez un article existant."
ITEM_TWICE = "Cet article figure déjà dans l’opération."
NO_QUANTITY = "Indiquez une quantité supérieure à zéro."
ALREADY_RECEIVED = "Cette commande est déjà réceptionnée."
ORDER_ITEM_TWICE = "Cet article figure déjà dans la commande."
COST_ON_ENTRY = "Seule une entrée a un prix."


# Named after their model rather than nested in it: the OpenAPI document names an
# enumeration after its class (see events/models.py).
class StockItemCategory(models.TextChoices):
    """The chips of the stock, in their order."""

    DRINKS = "drinks", "Boissons"
    FOOD = "food", "Alimentaire"
    SUPPLIES = "supplies", "Consommables"
    LOTTO_RAFFLE = "lotto_raffle", "Loto et tombola"


class StockOperationReason(models.TextChoices):
    """Why the stock moved. A purchase comes in, a consumption goes out, an
    adjustment goes either way; a stocktake and a delivery have their own
    screens.
    """

    PURCHASE = "purchase", "Achat"
    CONSUMPTION = "consumption", "Consommation"
    STOCKTAKE = "stocktake", "Inventaire"
    DELIVERY = "delivery", "Réception de commande"
    ADJUSTMENT = "adjustment", "Ajustement"


class StockDirection(models.TextChoices):
    """Which way an operation moves the stock (« Entrée ou sortie »)."""

    IN = "in", "Entrée"
    OUT = "out", "Sortie"


class StockItem(models.Model):
    """Goods the committee keeps, counted by the unit it is bought in: cans,
    bottles, kilograms of sweets, kegs…
    """

    name = models.CharField("nom", max_length=120)
    category = models.CharField("catégorie", max_length=20, choices=StockItemCategory.choices)
    # Written after a quantity: nothing, « kg », « fûts ».
    unit = models.CharField("unité", max_length=10, blank=True)
    # Below it, strictly, the item is low (A19). The validators place their
    # errors under the fields; the constraints keep the rules in the database.
    threshold = models.DecimalField(
        "seuil",
        max_digits=8,
        decimal_places=2,
        validators=[MinValueValidator(Decimal(0))],
    )
    # What the minus and plus buttons move.
    step = models.DecimalField(
        "pas",
        max_digits=8,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"), message=NO_STEP)],
    )
    # To the month, as the first of it (« mai 2027 »): shown, never alerted
    # (out of scope).
    best_before = models.DateField("DLUO", null=True, blank=True)
    # The unit cost of what came in before any purchase had its cost (D16): the
    # stock of before the costs, entered by hand or counted. Without it, the
    # first purchase paid above 0 € gives that cost. To the ten-thousandth: a
    # cup costs less than a cent.
    initial_cost = models.DecimalField(
        "prix de départ",
        max_digits=10,
        decimal_places=4,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal(0))],
    )

    class Meta:
        verbose_name = "article"
        verbose_name_plural = "articles"
        ordering = ["name", "pk"]
        constraints = [
            # An expression: Django places its error on the form, not on the name.
            models.UniqueConstraint(
                Lower("name"),
                name="stock_item_unique_name",
                violation_error_message="Un article porte déjà ce nom.",
            ),
            models.CheckConstraint(
                condition=Q(threshold__gte=0),
                name="stock_item_threshold_not_negative",
                violation_error_message="Le seuil ne peut pas être négatif.",
            ),
            models.CheckConstraint(
                condition=Q(step__gt=0),
                name="stock_item_step_positive",
                violation_error_message=NO_STEP,
            ),
            models.CheckConstraint(
                condition=Q(initial_cost__isnull=True) | Q(initial_cost__gte=0),
                name="stock_item_initial_cost_not_negative",
                violation_error_message="Le prix de départ ne peut pas être négatif.",
            ),
        ]

    def __str__(self):
        return self.name


class StockOperation(models.Model):
    """Movements made together, for one reason: the shopping of the bar, what
    a stocktake found, a delivery received, a click on minus or plus.
    """

    reason = models.CharField("motif", max_length=20, choices=StockOperationReason.choices)
    # « Courses buvette »; empty, the reason names the operation.
    label = models.CharField("libellé", max_length=200, blank=True)
    # An event deleted leaves its operations behind, without it: an operation
    # is never corrected, but for the costs of a purchase (D16), so refusing
    # would keep the event forever.
    event = models.ForeignKey(
        Event,
        verbose_name="événement",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_operations",
        error_messages=EVENT_ERROR_MESSAGES,
    )
    # The order a delivery received (7.4). A document deleted leaves the
    # delivery behind, without it: the stock keeps what came in.
    document = models.ForeignKey(
        Document,
        verbose_name="document",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_operations",
    )
    # A deleted account leaves its operations behind, without a name.
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="auteur",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_operations",
    )
    created_at = models.DateTimeField("enregistrée le", auto_now_add=True)

    class Meta:
        verbose_name = "opération du stock"
        verbose_name_plural = "opérations du stock"
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["document"],
                condition=Q(reason=StockOperationReason.DELIVERY),
                name="stock_operation_one_delivery_per_order",
                violation_error_code="unique",
                violation_error_message=ALREADY_RECEIVED,
            ),
        ]

    def __str__(self):
        return self.label or self.get_reason_display()


class StockMovement(models.Model):
    """What an operation changed of one item: positive in, negative out."""

    operation = models.ForeignKey(
        StockOperation,
        verbose_name="opération",
        on_delete=models.CASCADE,
        related_name="movements",
    )
    # An item that has moved keeps its history: it is not deleted.
    item = models.ForeignKey(
        StockItem,
        verbose_name="article",
        on_delete=models.PROTECT,
        related_name="movements",
        error_messages={"invalid": UNKNOWN_ITEM},
    )
    delta = models.DecimalField("variation", max_digits=10, decimal_places=2)
    # What its line of a purchase or a delivery cost, all taxes included (D16):
    # the amount paid, from which its unit cost comes. None until it is known;
    # 0 for a prize given.
    cost = models.DecimalField(
        "prix",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal(0))],
    )

    class Meta:
        verbose_name = "mouvement du stock"
        verbose_name_plural = "mouvements du stock"
        constraints = [
            models.CheckConstraint(
                condition=~Q(delta=0),
                name="stock_movement_some_delta",
                violation_error_message=NO_DELTA,
            ),
            models.CheckConstraint(
                condition=Q(cost__isnull=True) | (Q(cost__gte=0) & Q(delta__gt=0)),
                name="stock_movement_cost_on_entry",
                violation_error_message=COST_ON_ENTRY,
            ),
            models.UniqueConstraint(
                fields=["operation", "item"],
                name="stock_movement_unique_item",
                violation_error_message=ITEM_TWICE,
            ),
        ]

    def __str__(self):
        return f"{self.item} : {self.delta:+}"


class OrderLine(models.Model):
    """What an order brings to the stock (7.4): an item, and how much of it.
    Before the assistant, a member enters them from the order (A19).
    """

    # The lines go with their order.
    document = models.ForeignKey(
        Document,
        verbose_name="commande",
        on_delete=models.CASCADE,
        related_name="order_lines",
    )
    # An item an order names keeps its history: it is not deleted.
    item = models.ForeignKey(
        StockItem,
        verbose_name="article",
        on_delete=models.PROTECT,
        related_name="order_lines",
        error_messages={"invalid": UNKNOWN_ITEM},
    )
    quantity = models.DecimalField(
        "quantité",
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"), message=NO_QUANTITY)],
    )

    class Meta:
        verbose_name = "ligne de commande"
        verbose_name_plural = "lignes de commande"
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gt=0),
                name="order_line_some_quantity",
                violation_error_message=NO_QUANTITY,
            ),
            models.UniqueConstraint(
                fields=["document", "item"],
                name="order_line_unique_item",
                violation_error_message=ORDER_ITEM_TWICE,
            ),
        ]

    def __str__(self):
        return f"{self.item} : {self.quantity}"
