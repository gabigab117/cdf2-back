import re
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from documents.models import DocumentStatus, document_path
from tests.documents.factories import DocumentFactory

pytestmark = pytest.mark.django_db


def test_a_stored_file_is_named_by_a_random_uuid():
    """
    Given two files deposited under the same name
    When their place on disk is chosen
    Then each gets a random UUID, with the extension of its type, and nothing of its name
    """
    first = document_path(None, "facture-sono.pdf")
    second = document_path(None, "facture-sono.pdf")

    assert re.fullmatch(r"documents/[0-9a-f-]{36}\.pdf", first)
    assert first != second


def test_a_validated_document_carries_the_time_of_its_validation():
    """
    Given a document marked validated without the time it was, or the reverse
    When it is checked
    Then both are refused: a document is validated when, and only when, it is dated
    """
    undated = DocumentFactory.build(status=DocumentStatus.VALIDATED)
    dated = DocumentFactory.build(validated_at=timezone.now())

    for document in (undated, dated):
        with pytest.raises(ValidationError) as caught:
            document.full_clean(exclude={"uploaded_by"})
        assert caught.value.messages == ["Un document validé porte la date de sa validation."]


def test_an_amount_below_zero_is_refused():
    """
    Given a document whose amount is negative
    When it is checked
    Then the amount is refused, in French
    """
    document = DocumentFactory.build(amount=Decimal("-37.57"))

    with pytest.raises(ValidationError) as caught:
        document.full_clean(exclude={"uploaded_by"})

    assert caught.value.message_dict == {
        "amount": ["Assurez-vous que cette valeur est supérieure ou égale à 0."]
    }


def test_a_document_reads_as_its_title():
    """
    Given a document
    When it is named, as the Django admin would
    Then it reads as its title
    """
    assert str(DocumentFactory.build(title="Facture — Location sono")) == "Facture — Location sono"
