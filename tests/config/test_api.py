import json
from collections import Counter

from django.apps import apps
from django.conf import settings as django_settings
from django.core.exceptions import ValidationError
from django.db.models import Choices
from django.http import Http404
from ninja import Schema
from ninja.errors import ValidationError as SchemaValidationError

from config.api import django_validation_error, not_found, schema_validation_error

# Operations open without authentication, each declared with auth=None.
PUBLIC_OPERATIONS = {
    ("get", "/api/health"),
    ("post", "/api/auth/login"),
    ("post", "/api/auth/refresh"),
    ("post", "/api/auth/logout"),
    ("get", "/api/public/events"),
    ("get", "/api/public/events/{slug}"),
    ("get", "/api/public/events/{slug}.ics"),
    ("get", "/api/public/agenda"),
    ("get", "/api/public/agenda.ics"),
}


def test_schema_is_served_where_enabled(client, settings):
    """
    Given an environment that serves the API schema
    When the schema is requested
    Then the OpenAPI document of the project's API is returned
    """
    settings.SERVE_API_SCHEMA = True

    response = client.get("/api/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Comité des fêtes d'Ons-en-Bray"


def test_schema_and_docs_are_hidden_where_disabled(client, settings):
    """
    Given an environment that does not serve the API schema, like production
    When the schema or the interactive docs are requested
    Then both are reported as not found
    """
    settings.SERVE_API_SCHEMA = False

    assert client.get("/api/openapi.json").status_code == 404
    assert client.get("/api/docs").status_code == 404


def test_service_validation_errors_become_422_responses(rf):
    """
    Given a service that raises Django's ValidationError
    When the API translates the exception
    Then the response is a 422 listing each error with its location
    """
    response = django_validation_error(rf.get("/api/"), ValidationError({"name": ["Requis."]}))

    assert response.status_code == 422
    assert json.loads(response.content) == {
        "detail": [{"type": "validation_error", "loc": ["body", "name"], "msg": "Requis."}]
    }


def test_schema_validation_errors_become_422_responses_in_french(rf):
    """
    Given a request whose body lacks a key its schema requires
    When the API translates Ninja's exception
    Then the response is a 422 locating the key, with a message in French
    """
    error = SchemaValidationError(
        [{"type": "missing", "loc": ("body", "payload", "title"), "msg": "Field required"}]
    )

    response = schema_validation_error(rf.get("/api/"), error)

    assert response.status_code == 422
    assert json.loads(response.content) == {
        "detail": [
            {
                "type": "missing",
                "loc": ["body", "payload", "title"],
                "msg": "Ce champ est obligatoire.",
            }
        ]
    }


def test_not_found_answers_in_french(rf):
    """
    Given an operation that finds nothing at the requested address
    When the API translates the exception
    Then the response is a 404, with a message in French
    """
    response = not_found(rf.get("/api/"), Http404())

    assert response.status_code == 404
    assert json.loads(response.content) == {"detail": "Introuvable."}


def test_every_operation_is_private_unless_declared_public(client, settings):
    """
    Given the operations published in the API schema
    When their security is reviewed
    Then only the known public operations skip authentication
    And every other one declares its 401 and 403 answers
    """
    settings.SERVE_API_SCHEMA = True

    paths = client.get("/api/openapi.json").json()["paths"]

    for path, operations in paths.items():
        for method, operation in operations.items():
            if "security" in operation:
                assert {"401", "403"} <= operation["responses"].keys(), (method, path)
            else:
                assert (method, path) in PUBLIC_OPERATIONS


def test_every_collection_comes_by_page(client, settings):
    """
    Given the operations published in the API schema
    When their successful answers are reviewed
    Then none is a bare list: a collection comes by page, with its count
    """
    settings.SERVE_API_SCHEMA = True

    paths = client.get("/api/openapi.json").json()["paths"]

    for path, operations in paths.items():
        for method, operation in operations.items():
            for status, answer in operation["responses"].items():
                schema = answer.get("content", {}).get("application/json", {}).get("schema", {})
                if status.startswith("2"):
                    assert schema.get("type") != "array", (method, path)


def references(node):
    """The names of the schemas a part of the OpenAPI document refers to."""
    if isinstance(node, dict):
        if "$ref" in node:
            yield node["$ref"].rsplit("/", 1)[-1]
        for value in node.values():
            yield from references(value)
    elif isinstance(node, list):
        for value in node:
            yield from references(value)


def answer_schemas(document, site):
    """The object schemas of the successful answers, at any depth, of the public
    site's operations, or of all the others.
    """
    schemas = document["components"]["schemas"]
    to_visit = {
        name
        for path, operations in document["paths"].items()
        if path.startswith("/api/public/") == site
        for operation in operations.values()
        for status, answer in operation["responses"].items()
        if status.startswith("2")
        for name in references(answer)
    }
    visited = set()
    while to_visit:
        name = to_visit.pop()
        visited.add(name)
        to_visit |= set(references(schemas[name])) - visited
    return {name for name in visited if "properties" in schemas[name]}


def test_the_site_answers_with_schemas_of_its_own(client, settings):
    """
    Given the operations of the public site and all the others
    When the schemas of their successful answers are compared, choices aside
    Then the site shares none: a field added for the board would reach it
    """
    settings.SERVE_API_SCHEMA = True

    document = client.get("/api/openapi.json").json()

    site = answer_schemas(document, site=True)
    assert {"PagedPublicEventItemOut", "PublicEventOut", "AgendaOut"} <= site
    assert site & answer_schemas(document, site=False) == set()


def subclasses(cls):
    for subclass in cls.__subclasses__():
        yield subclass
        yield from subclasses(subclass)


def test_schemas_and_choices_have_unique_names():
    """
    Given the schemas and the choices the project's apps declare
    When the OpenAPI document is built, naming each after its class
    Then no two share a name: one would silently replace the other in the
    document, and in the front end's types
    """
    project_apps = {
        app.name
        for app in apps.get_app_configs()
        if app.path.startswith(str(django_settings.BASE_DIR)) and ".venv" not in app.path
    }
    names = Counter(
        cls.__name__
        for cls in {*subclasses(Schema), *subclasses(Choices)}
        if cls.__module__.split(".")[0] in project_apps
    )

    assert {"events", "accounts", "core", "dashboard", "notes", "tasks"} <= project_apps
    assert [name for name, count in names.items() if count > 1] == []
