from django.shortcuts import get_object_or_404
from ninja import Router, Status

from core.schemas import ErrorOut, ValidationErrorOut
from documents.models import Document, DocumentCategory
from stock.models import StockItem
from stock.schemas import (
    OrderLinesIn,
    StockAdjustmentIn,
    StockedItemOut,
    StockItemIn,
    StockItemOut,
    StockOperationIn,
    StockOperationOut,
    StockOrderOut,
    StockOverviewOut,
    StocktakeIn,
)
from stock.services.items import create_item, delete_item, update_item
from stock.services.movements import adjust
from stock.services.operations import record_operation, record_stocktake
from stock.services.orders import cancel_delivery, order, orders, receive, replace_lines
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


def _order(document_id: int) -> Document:
    """An order document: any other document is not one of the stock's."""
    return get_object_or_404(Document, pk=document_id, category=DocumentCategory.ORDER)


@router.get(
    "/stock/orders/{document_id}",
    response={200: StockOrderOut, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut},
    summary="Read the lines and the delivery of an order",
)
def read_order(request, document_id: int):
    """What an order brings to the stock, and whether it was received."""
    return order(get_object_or_404(orders(), pk=document_id))


@router.put(
    "/stock/orders/{document_id}/lines",
    response={200: StockOrderOut, 400: ErrorOut, **REFUSALS},
    summary="Write the lines of an order",
)
def write_order_lines(request, document_id: int, payload: OrderLinesIn):
    """The lines of an order, all at once, until it is received: without any,
    the order leaves the Stock page.
    """
    return replace_lines(_order(document_id), payload)


@router.post(
    "/stock/orders/{document_id}/delivery",
    response={200: StockOrderOut, **REFUSALS},
    summary="Receive the delivery of an order",
)
def receive_delivery(request, document_id: int):
    """« Réceptionner la livraison »: each line of a validated order comes into
    the stock, by a single delivery of the member.
    """
    return receive(_order(document_id), request.auth)


@router.delete(
    "/stock/orders/{document_id}/delivery",
    response={200: StockOrderOut, **REFUSALS},
    summary="Cancel the delivery of an order",
)
def cancel_order_delivery(request, document_id: int):
    """« Annuler »: the delivery is undone the day it was received, unless some
    of it has left the stock, or a stocktake has counted it, since.
    """
    return cancel_delivery(_order(document_id))
