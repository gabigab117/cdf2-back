from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from stock.models import StockOperationReason
from tests.stock.factories import StockItemFactory, StockMovementFactory, StockOperationFactory

pytestmark = pytest.mark.django_db


def errors_of(model):
    with pytest.raises(ValidationError) as error:
        model.full_clean()
    return error.value.message_dict


def test_an_item_reads_as_its_name():
    """
    Given an item « Jus de fruits 1 L »
    When it is shown in a shell or a log
    Then it reads as its name
    """
    assert str(StockItemFactory.build(name="Jus de fruits 1 L")) == "Jus de fruits 1 L"


@pytest.mark.parametrize(
    ("label", "shown"), [("Courses buvette", "Courses buvette"), ("", "Ajustement")]
)
def test_an_operation_reads_as_its_label_or_else_its_reason(label, shown):
    """
    Given an adjustment labelled « Courses buvette », and one without a label
    When it is shown in a shell or a log
    Then it reads as its label, or else as its reason
    """
    operation = StockOperationFactory.build(reason=StockOperationReason.ADJUSTMENT, label=label)

    assert str(operation) == shown


def test_a_movement_reads_as_its_item_and_its_signed_delta():
    """
    Given 24 cans out
    When the movement is shown in a shell or a log
    Then it reads as the item and the signed delta
    """
    movement = StockMovementFactory.build(
        item=StockItemFactory.build(name="Canettes"), delta=Decimal("-24.00")
    )

    assert str(movement) == "Canettes : -24.00"


def test_a_threshold_is_never_negative():
    """
    Given an item whose threshold is below zero
    When it is checked, then written
    Then its threshold is refused, and the database refuses it too
    """
    item = StockItemFactory.build(threshold=Decimal(-1))

    assert errors_of(item) == {
        "threshold": ["Assurez-vous que cette valeur est supérieure ou égale à 0."]
    }
    with pytest.raises(IntegrityError):
        item.save()


@pytest.mark.parametrize("step", [Decimal(0), Decimal("-0.5")])
def test_a_step_is_more_than_zero(step):
    """
    Given an item whose step is nothing, or below zero
    When it is checked, then written
    Then its step is refused, and the database refuses it too
    """
    item = StockItemFactory.build(step=step)

    assert errors_of(item) == {"step": ["Indiquez un pas supérieur à zéro."]}
    with pytest.raises(IntegrityError):
        item.save()


def test_two_items_never_share_a_name_whatever_its_case():
    """
    Given « Jus de fruits 1 L » in stock
    When « JUS DE FRUITS 1 l » is checked, then written
    Then it is refused, and the database refuses it too
    """
    StockItemFactory(name="Jus de fruits 1 L")
    item = StockItemFactory.build(name="JUS DE FRUITS 1 l")

    assert errors_of(item) == {"__all__": ["Un article porte déjà ce nom."]}
    with pytest.raises(IntegrityError):
        item.save()


def test_a_movement_changes_the_quantity():
    """
    Given a movement of nothing
    When it is checked, then written
    Then it is refused, and the database refuses it too
    """
    movement = StockMovementFactory.build(
        operation=StockOperationFactory(), item=StockItemFactory(), delta=Decimal(0)
    )

    assert errors_of(movement) == {"__all__": ["Un mouvement change la quantité."]}
    with pytest.raises(IntegrityError):
        movement.save()


def test_an_operation_moves_an_item_once():
    """
    Given an operation that moves the juice already
    When a second movement of the juice is checked, then written
    Then it is refused, and the database refuses it too
    """
    first = StockMovementFactory()
    movement = StockMovementFactory.build(operation=first.operation, item=first.item)

    assert errors_of(movement) == {"__all__": ["Cet article figure déjà dans l’opération."]}
    with pytest.raises(IntegrityError):
        movement.save()
