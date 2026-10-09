import json

from django.core.exceptions import ValidationError

from config.api import django_validation_error

# Operations open without authentication, each declared with auth=None.
PUBLIC_OPERATIONS = {
    ("get", "/api/health"),
    ("post", "/api/auth/login"),
    ("post", "/api/auth/refresh"),
    ("post", "/api/auth/logout"),
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
