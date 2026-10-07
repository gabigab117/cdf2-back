from django.core.exceptions import NON_FIELD_ERRORS, ValidationError

from core.errors import validation_error_details


def test_field_errors_are_located_under_their_field():
    """
    Given a validation error on a field and an error without a field
    When it is converted for the API
    Then each message is located under its field, or under the body
    """
    error = ValidationError(
        {"name": ["Ce champ est obligatoire."], NON_FIELD_ERRORS: ["Conflit de dates."]}
    )

    assert validation_error_details(error) == [
        {"type": "validation_error", "loc": ["body", "name"], "msg": "Ce champ est obligatoire."},
        {"type": "validation_error", "loc": ["body"], "msg": "Conflit de dates."},
    ]


def test_errors_raised_without_fields_are_located_under_the_body():
    """
    Given a validation error raised as a plain list of messages
    When it is converted for the API
    Then every message is located under the body
    """
    error = ValidationError(["Premier problème.", "Second problème."])

    assert validation_error_details(error) == [
        {"type": "validation_error", "loc": ["body"], "msg": "Premier problème."},
        {"type": "validation_error", "loc": ["body"], "msg": "Second problème."},
    ]
