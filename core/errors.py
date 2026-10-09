"""Translation of service errors into API error payloads."""

from django.core.exceptions import NON_FIELD_ERRORS, ValidationError

Location = list[str | int]
ErrorItem = dict[str, str | Location]


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


def _path(field: str) -> Location:
    return [int(part) if part.isdigit() else part for part in field.split(".")]


def _item(location: Location, message: str) -> ErrorItem:
    return {"type": "validation_error", "loc": location, "msg": message}
