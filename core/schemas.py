from ninja import Schema
from pydantic import ConfigDict


class HealthOut(Schema):
    database: bool
    release: str


class InputSchema(Schema):
    """Base of every input schema: texts lose their surrounding spaces.

    A field kept exactly as typed, like a password, opts out with
    `Annotated[str, StringConstraints(strip_whitespace=False)]`.
    """

    model_config = ConfigDict(str_strip_whitespace=True)


class ErrorOut(Schema):
    detail: str


class ValidationErrorItem(Schema):
    type: str
    loc: list[str | int]
    msg: str


class ValidationErrorOut(Schema):
    """A 422 answer: one item per error, located under its field (core/errors.py)."""

    detail: list[ValidationErrorItem]
