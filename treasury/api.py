from django.shortcuts import get_object_or_404
from ninja import Form, Query, Router, Status
from ninja.pagination import paginate

from core.schemas import ErrorOut, ValidationErrorOut
from treasury.models import LedgerEntry
from treasury.schemas import (
    FiscalYearQuery,
    FiscalYearResultsOut,
    LedgerEntryFilters,
    LedgerEntryIn,
    LedgerEntryOut,
    NewLedgerEntryIn,
)
from treasury.services.entries import delete_entry, ledger_entries, record_entry, update_entry
from treasury.services.results import fiscal_year_results

router = Router(tags=["treasury"])

# What every operation on an existing entry may answer besides its success.
REFUSALS = {401: ErrorOut, 403: ErrorOut, 404: ErrorOut, 422: ValidationErrorOut}


@router.get(
    "/treasury/results",
    response={200: FiscalYearResultsOut, 401: ErrorOut, 403: ErrorOut, 422: ValidationErrorOut},
    summary="Read the results of a fiscal year",
)
def read_results(request, query: Query[FiscalYearQuery]):
    """What a fiscal year brought in and cost: in all, for each event that has
    entries in it, the first to start first, then for the general running.
    """
    return fiscal_year_results(query.year)


@router.get(
    "/treasury/entries",
    response={200: list[LedgerEntryOut], 401: ErrorOut, 403: ErrorOut, 422: ValidationErrorOut},
    summary="List the ledger entries",
)
@paginate
def list_entries(request, filters: Query[LedgerEntryFilters]):
    """The journal, by page, the latest entry first."""
    return filters.filter(ledger_entries())


@router.post(
    "/treasury/entries",
    response={
        201: LedgerEntryOut,
        400: ErrorOut,
        401: ErrorOut,
        403: ErrorOut,
        422: ValidationErrorOut,
    },
    summary="Record a ledger entry",
)
def record(request, payload: Form[NewLedgerEntryIn]):
    """Record an entry, from the form of the journal: a field left empty is not sent."""
    return Status(201, record_entry(payload, request.auth))


@router.get(
    "/treasury/entries/{entry_id}",
    response={200: LedgerEntryOut, **REFUSALS},
    summary="Read a ledger entry",
)
def read_entry(request, entry_id: int):
    return get_object_or_404(ledger_entries(), pk=entry_id)


@router.put(
    "/treasury/entries/{entry_id}",
    response={200: LedgerEntryOut, 400: ErrorOut, **REFUSALS},
    summary="Correct a ledger entry",
)
def correct(request, entry_id: int, payload: LedgerEntryIn):
    """Rewrite an entry whole: its receipt and its reimbursement stay as they are."""
    return update_entry(get_object_or_404(LedgerEntry, pk=entry_id), payload)


@router.delete(
    "/treasury/entries/{entry_id}",
    response={204: None, **REFUSALS},
    summary="Delete a ledger entry",
)
def delete(request, entry_id: int):
    """Delete an entry: its receipt stays among the documents."""
    delete_entry(get_object_or_404(LedgerEntry, pk=entry_id))
    return Status(204, None)
