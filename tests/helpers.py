"""Helpers the tests of every app share."""

import datetime as dt

import pytest
from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone


def iso(moment):
    """A time as the API writes it: to the millisecond, as Django's JSON does."""
    return DjangoJSONEncoder().default(moment)


def send(client, method, path, payload=None):
    """A request with a JSON body, as the front end sends its writes."""
    return getattr(client, method)(path, payload, content_type="application/json")


def member_json(member):
    """A board member as the API writes them."""
    return {
        "id": member.id,
        "first_name": member.first_name,
        "last_name": member.last_name,
        "email": member.email,
    }


def messages(response):
    """The location and the message of each error of a 422."""
    return [(error["loc"], error["msg"]) for error in response.json()["detail"]]


def messages_by_place(response):
    """The messages of a 422, by where the API placed them."""
    assert response.status_code == 422
    return {tuple(error["loc"]): error["msg"] for error in response.json()["detail"]}


def ahead(days):
    """The day so many days from today, in Paris."""
    return timezone.localdate() + dt.timedelta(days=days)


def errors_of(instance):
    """The messages, by field, that full_clean() refuses an instance with."""
    with pytest.raises(ValidationError) as error:
        instance.full_clean()
    return error.value.message_dict
