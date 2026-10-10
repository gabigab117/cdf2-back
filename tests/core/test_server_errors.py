"""Server errors are emailed to the administrators by Django's own handler (D11)."""

import pytest


def fail():
    raise RuntimeError("database driver crashed")


@pytest.fixture
def failing_api(client, monkeypatch):
    """A client whose next call to the API fails on an unexpected error."""
    monkeypatch.setattr("core.api.database_is_available", fail)
    # The response is the one Django gives the browser, not the exception.
    client.raise_request_exception = False
    return client


def test_a_server_error_is_emailed_to_the_administrators(failing_api, settings, mailoutbox):
    """
    Given an administrator to email
    When an operation fails on an unexpected error
    Then the API answers 500
    And the administrator receives the error by email, with its traceback
    """
    settings.ADMINS = ["admin@example.org"]

    response = failing_api.get("/api/health")

    assert response.status_code == 500
    [email] = mailoutbox
    assert email.to == ["admin@example.org"]
    assert (
        email.subject
        == "[Comité des fêtes] ERROR (EXTERNAL IP): Internal Server Error: /api/health"
    )
    assert "RuntimeError at /api/health\ndatabase driver crashed" in email.body


def test_a_server_error_emails_nobody_without_administrators(failing_api, settings, mailoutbox):
    """
    Given no administrator to email, as on the preproduction
    When an operation fails on an unexpected error
    Then the API answers 500
    And no email is sent
    """
    settings.ADMINS = []

    response = failing_api.get("/api/health")

    assert response.status_code == 500
    assert mailoutbox == []
