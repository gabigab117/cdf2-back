"""Helpers the tests of every app share."""

from django.core.serializers.json import DjangoJSONEncoder


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
