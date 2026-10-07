"""Health of the service, as reported to the deployment and to monitoring."""

from django.db import DatabaseError, connection


def database_is_available() -> bool:
    """Tell whether the database answers a trivial query."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except DatabaseError:
        return False
    return True
