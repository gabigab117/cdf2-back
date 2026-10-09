"""Translation of validation errors into API error payloads.

Two kinds of errors become the same 422 items, holding a type, a location and a
message in French: those of the request's schemas, raised by Ninja, and those
of the services, raised as Django's ValidationError.
"""

from typing import Any

from django import forms
from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.core.validators import MinValueValidator, RegexValidator
from django.utils.functional import Promise
from ninja.errors import ValidationError as SchemaValidationError

Location = list[str | int]
ErrorItem = dict[str, str | Location]

# Pydantic writes its messages in English only. As its documentation suggests,
# they are replaced after their error type, which never changes, with the
# French messages Django already translates: those of its form fields, the only
# ones without a "%(value)s" to fill, Ninja leaving the input out of its errors.
_SCHEMA_MESSAGES: dict[str, Promise] = {
    "missing": forms.Field.default_error_messages["required"],
    "enum": forms.ModelChoiceField.default_error_messages["invalid_choice"],
    "literal_error": forms.ModelChoiceField.default_error_messages["invalid_choice"],
    "int_parsing": forms.IntegerField.default_error_messages["invalid"],
    "int_type": forms.IntegerField.default_error_messages["invalid"],
    "int_from_float": forms.IntegerField.default_error_messages["invalid"],
    "int_parsing_size": forms.IntegerField.default_error_messages["invalid"],
    "float_parsing": forms.FloatField.default_error_messages["invalid"],
    "float_type": forms.FloatField.default_error_messages["invalid"],
    "finite_number": forms.FloatField.default_error_messages["invalid"],
    "datetime_from_date_parsing": forms.DateTimeField.default_error_messages["invalid"],
    "datetime_parsing": forms.DateTimeField.default_error_messages["invalid"],
    "datetime_type": forms.DateTimeField.default_error_messages["invalid"],
    # A date without its time zone: the board never types one, the front end
    # adds it, so the member is only told the date is not valid.
    "timezone_aware": forms.DateTimeField.default_error_messages["invalid"],
    "time_parsing": forms.TimeField.default_error_messages["invalid"],
    "time_type": forms.TimeField.default_error_messages["invalid"],
    "list_type": forms.MultipleChoiceField.default_error_messages["invalid_list"],
}


def validation_error_details(error: ValidationError) -> list[ErrorItem]:
    """Convert a Django ValidationError into the items of a 422 response.

    Ninja reports request validation errors as items holding a type, a location
    and a message. Errors raised by the services take the same shape, so that
    the front end maps both onto the form fields with a single normaliser: a
    field error is located under its field name, an error without a field under
    the body itself. A service names a field of a list item by its dotted path,
    "programme.2.title", located like Ninja's ["body", "programme", 2, "title"].
    """
    if not hasattr(error, "error_dict"):
        return [_item(["body"], message) for message in error.messages]
    return [
        _item(["body"] if field == NON_FIELD_ERRORS else ["body", *_path(field)], message)
        for field, messages in error.message_dict.items()
        for message in messages
    ]


def schema_error_details(error: SchemaValidationError) -> list[ErrorItem]:
    """Convert the errors of a request's schemas into the items of a 422 response.

    Each keeps the type and location Ninja gave it, and receives a message in
    French. Nothing else is kept: the context of an error is not part of the
    API's contract.
    """
    return [
        {"type": item["type"], "loc": list(item["loc"]), "msg": _schema_message(item)}
        for item in error.errors
    ]


def _schema_message(item: dict[str, Any]) -> str:
    if item["type"] == "greater_than_equal":
        return MinValueValidator.message % {"limit_value": item["ctx"]["ge"]}
    # Any other type, such as a text expected and something else given, only
    # comes from a request no form of the board sends.
    return str(_SCHEMA_MESSAGES.get(item["type"], RegexValidator.message))


def _path(field: str) -> Location:
    return [int(part) if part.isdigit() else part for part in field.split(".")]


def _item(location: Location, message: str) -> ErrorItem:
    return {"type": "validation_error", "loc": location, "msg": message}
