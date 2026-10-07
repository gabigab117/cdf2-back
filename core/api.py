from django.conf import settings
from ninja import Router, Status

from core.schemas import HealthOut
from core.services.health import database_is_available

router = Router(tags=["health"])


@router.get(
    "/health",
    auth=None,
    response={200: HealthOut, 503: HealthOut},
    summary="Service health",
)
def health(request):
    """Report whether the service can answer, and which release is running."""
    database = database_is_available()
    return Status(200 if database else 503, {"database": database, "release": settings.RELEASE_SHA})
