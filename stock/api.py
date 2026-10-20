from django.shortcuts import get_object_or_404
from ninja import Router, Status

from core.schemas import ErrorOut, ValidationErrorOut
from stock.models import StockItem
from stock.schemas import (
    StockAdjustmentIn,
    StockedItemOut,
    StockItemIn,
    StockItemOut,
    StockOperationIn,
    StockOperationOut,
    StockOverviewOut,
    StocktakeIn,
)
from stock.services.items import create_item, delete_item, update_item
from stock.services.movements import adjust
from stock.services.operations import record_operation, record_stocktake
from stock.services.overview import stock_overview

router = Router(tags=["stock"])

# What every operation on an existing item may answer besides its success.
REFUSALS = {401: ErrorOut, 403: ErrorOut, 404: ErrorOut, 422: ValidationErrorOut}

# What an operation that records a body may answer besides its success.
WRITE_REFUSALS = {400: ErrorOut, 401: ErrorOut, 403: ErrorOut, 422: ValidationErrorOut}


@router.get(
    "/stock",
    response={200: StockOverviewOut, 401: ErrorOut, 403: ErrorOut},
    summary="Read the stock",
)
def read_stock(request):
    """Every item, by category then by name, with its quantity, whether it is
    low and how full its bar is; the figures of the chips; the latest stocktake;
    the latest operations.
    """
    return stock_overview()


@router.post(
    "/stock/operations",
    response={201: StockOperationOut, **WRITE_REFUSALS},
    summary="Record an entry or an exit of the stock",
)
def record_entry_or_exit(request, payload: StockOperationIn):
    """« Entrée ou sortie »: several items in or out at once, for one reason,
    recorded with the member. An exit never takes more than is in stock.
    """
    return Status(201, record_operation(payload, request.auth))


@router.post(
    "/stock/stocktakes",
    response={201: StockOperationOut, **WRITE_REFUSALS},
    summary="Record a stocktake",
)
def take_stock(request, payload: StocktakeIn):
    """« Faire l'inventaire »: each difference between what was counted and
    what the stock held becomes a movement of a single stocktake.
    """
    return Status(201, record_stocktake(payload, request.auth))


@router.post(
    "/stock/items",
    response={201: StockItemOut, **WRITE_REFUSALS},
    summary="Add a stock item",
)
def create(request, payload: StockItemIn):
    return Status(201, create_item(payload))


@router.put(
    "/stock/items/{item_id}",
    response={200: StockItemOut, 400: ErrorOut, **REFUSALS},
    summary="Correct a stock item",
)
def correct(request, item_id: int, payload: StockItemIn):
    """Rewrite an item whole: its movements stay as they are."""
    return update_item(get_object_or_404(StockItem, pk=item_id), payload)


@router.delete(
    "/stock/items/{item_id}",
    response={204: None, **REFUSALS},
    summary="Delete a stock item",
)
def delete(request, item_id: int):
    """Delete an item that has never moved: the history keeps the others."""
    delete_item(get_object_or_404(StockItem, pk=item_id))
    return Status(204, None)


@router.post(
    "/stock/items/{item_id}/adjustments",
    response={200: StockedItemOut, 400: ErrorOut, **REFUSALS},
    summary="Adjust a stock item by its step",
)
def adjust_item(request, item_id: int, payload: StockAdjustmentIn):
    """A click on minus or plus: the item's step, in or out, recorded with the member.
    Out, what is left when less than a step is.
    """
    return adjust(get_object_or_404(StockItem, pk=item_id), payload.direction, request.auth)
