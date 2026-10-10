from ninja import Router

from core.schemas import ErrorOut
from dashboard.schemas import BoardOverviewOut
from dashboard.services.overview import board_overview

router = Router(tags=["dashboard"])


@router.get(
    "/overview",
    response={200: BoardOverviewOut, 401: ErrorOut, 403: ErrorOut},
    summary="Board overview",
)
def overview(request):
    """The dashboard's figures, whole: a bounded aggregate, never paginated."""
    return board_overview()
