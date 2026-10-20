"""Helpers the tests of every app share."""

from django.core.serializers.json import DjangoJSONEncoder


def iso(moment):
    """A time as the API writes it: to the millisecond, as Django's JSON does."""
    return DjangoJSONEncoder().default(moment)


def send(client, method, path, payload=None):
    """A request with a JSON body, as the front end sends its writes."""
    return getattr(client, method)(path, payload, content_type="application/json")
