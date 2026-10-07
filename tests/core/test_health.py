import pytest
from django.db import OperationalError

from core.services.health import database_is_available


@pytest.mark.django_db
def test_health_reports_the_running_release(client, settings):
    """
    Given a reachable database and a deployed release
    When the health endpoint is called without credentials
    Then it answers 200 with the database available and the release's SHA
    """
    settings.RELEASE_SHA = "3f2c1a"

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"database": True, "release": "3f2c1a"}


def test_health_reports_an_unavailable_database(client, monkeypatch):
    """
    Given a database that does not answer
    When the health endpoint is called
    Then it answers 503 with the database reported unavailable
    """
    monkeypatch.setattr("core.api.database_is_available", lambda: False)

    response = client.get("/api/health")

    assert response.status_code == 503
    assert response.json()["database"] is False


@pytest.mark.django_db
def test_database_is_available_when_it_answers():
    """
    Given a reachable database
    When its availability is checked
    Then it is reported available
    """
    assert database_is_available() is True


def test_database_is_unavailable_when_the_query_fails(monkeypatch):
    """
    Given a database connection that fails
    When its availability is checked
    Then it is reported unavailable instead of raising
    """

    class BrokenConnection:
        def cursor(self):
            raise OperationalError("connection refused")

    monkeypatch.setattr("core.services.health.connection", BrokenConnection())

    assert database_is_available() is False
