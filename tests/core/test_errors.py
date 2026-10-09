import pytest
from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from ninja.errors import ValidationError as SchemaValidationError

from core.errors import schema_error_details, validation_error_details

CHOICE = "Sélectionnez un choix valide. Ce choix ne fait pas partie de ceux disponibles."
WHOLE_NUMBER = "Saisissez un nombre entier."
NUMBER = "Saisissez un nombre."
DATE_AND_TIME = "Saisissez une date et une heure valides."
TIME = "Saisissez une heure valide."
VALUE = "Saisissez une valeur valide."


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


def test_errors_of_a_list_item_are_located_by_their_path():
    """
    Given a validation error on the title of the third line of a list
    When it is converted for the API
    Then it is located like Ninja's own errors, the position as a number
    """
    error = ValidationError({"programme.2.title": ["Ce champ ne peut pas être vide."]})

    assert validation_error_details(error) == [
        {
            "type": "validation_error",
            "loc": ["body", "programme", 2, "title"],
            "msg": "Ce champ ne peut pas être vide.",
        }
    ]


@pytest.mark.parametrize(
    ("error_type", "message"),
    [
        ("missing", "Ce champ est obligatoire."),
        ("enum", CHOICE),
        ("literal_error", CHOICE),
        ("int_parsing", WHOLE_NUMBER),
        ("int_type", WHOLE_NUMBER),
        ("int_from_float", WHOLE_NUMBER),
        ("int_parsing_size", WHOLE_NUMBER),
        ("float_parsing", NUMBER),
        ("float_type", NUMBER),
        ("finite_number", NUMBER),
        ("datetime_from_date_parsing", DATE_AND_TIME),
        ("datetime_parsing", DATE_AND_TIME),
        ("datetime_type", DATE_AND_TIME),
        ("timezone_aware", DATE_AND_TIME),
        ("time_parsing", TIME),
        ("time_type", TIME),
        ("list_type", "Saisissez une liste de valeurs."),
        ("string_type", VALUE),
        ("bool_parsing", VALUE),
    ],
)
def test_schema_errors_are_worded_in_french_after_their_type(error_type, message):
    """
    Given an error of a request's schema, with Pydantic's message in English
    When it is converted for the API
    Then its message is the French one of its type, or a generic one
    """
    error = SchemaValidationError(
        [{"type": error_type, "loc": ("body", "payload", "title"), "msg": "In English."}]
    )

    assert schema_error_details(error) == [
        {"type": error_type, "loc": ["body", "payload", "title"], "msg": message}
    ]


def test_schema_errors_keep_their_type_and_location_only():
    """
    Given an error of a request's schema that comes with its context
    When it is converted for the API
    Then it keeps its type and its location, as a list, and nothing else
    """
    error = SchemaValidationError(
        [
            {
                "type": "enum",
                "loc": ("body", "payload", "programme", 2, "icon"),
                "msg": "Input should be 'people' or 'home'",
                "ctx": {"expected": "'people' or 'home'"},
            }
        ]
    )

    assert schema_error_details(error) == [
        {"type": "enum", "loc": ["body", "payload", "programme", 2, "icon"], "msg": CHOICE}
    ]


def test_a_lower_bound_error_states_its_bound():
    """
    Given a number of the query string below the least value it accepts, 1
    When the error is converted for the API
    Then its message states that bound
    """
    error = SchemaValidationError(
        [
            {
                "type": "greater_than_equal",
                "loc": ("query", "page_size"),
                "msg": "Input should be greater than or equal to 1",
                "ctx": {"ge": 1},
            }
        ]
    )

    assert schema_error_details(error)[0]["msg"] == (
        "Assurez-vous que cette valeur est supérieure ou égale à 1."
    )
