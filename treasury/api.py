from django.shortcuts import get_object_or_404
from ninja import File, Form, Query, Router, Status, UploadedFile
from ninja.pagination import paginate

from core.schemas import ErrorOut, ValidationErrorOut
from documents.models import Document
from documents.schemas import DocumentOut
from treasury.models import LedgerEntry
from treasury.schemas import (
    FiscalYearQuery,
    FiscalYearResultsOut,
    GeneralMeetingReportOut,
    InvoiceAttachIn,
    InvoiceExpenseIn,
    LedgerEntryFilters,
    LedgerEntryIn,
    LedgerEntryOut,
    NewLedgerEntryIn,
    ReimbursementIn,
)
from treasury.services.entries import (
    attach_receipt,
    delete_entry,
    ledger_entries,
    record_entry,
    update_entry,
)
from treasury.services.invoices import attach_invoice, create_invoice_expense
from treasury.services.reimbursements import cancel_reimbursement, mark_reimbursed
from treasury.services.report import general_meeting_report
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
    "/treasury/report",
    response={200: GeneralMeetingReportOut, 401: ErrorOut, 403: ErrorOut, 422: ValidationErrorOut},
    summary="Read the report of a fiscal year for the general meeting",
)
def read_report(request, query: Query[FiscalYearQuery]):
    """« Bilan pour l'AG »: the totals and results of a fiscal year, what each
    category brought in or cost, and the expenses missing their receipt.
    """
    return general_meeting_report(query.year)


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
def record(request, payload: Form[NewLedgerEntryIn], file: File[UploadedFile | None] = None):
    """Record an entry, from the form of the journal: a field left empty is not
    sent. A file sent with it is its receipt, filed among the documents.
    """
    return Status(201, record_entry(payload, request.auth, file))


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


@router.post(
    "/treasury/entries/{entry_id}/receipt",
    response={200: LedgerEntryOut, 400: ErrorOut, **REFUSALS},
    summary="Join the receipt of a ledger entry",
)
def join_receipt(request, entry_id: int, file: File[UploadedFile]):
    """« Joindre le justificatif »: the document that proves an entry that has
    none, filed among the documents.
    """
    return attach_receipt(get_object_or_404(LedgerEntry, pk=entry_id), file, request.auth)


@router.post(
    "/treasury/entries/{entry_id}/reimbursement",
    response={200: LedgerEntryOut, 400: ErrorOut, **REFUSALS},
    summary="Mark an advance reimbursed",
)
def reimburse(request, entry_id: int, payload: ReimbursementIn):
    """« Marquer remboursée »: the advance of a member is paid back, its line
    completed; no second expense is written (A18).
    """
    return mark_reimbursed(get_object_or_404(LedgerEntry, pk=entry_id), payload)


@router.delete(
    "/treasury/entries/{entry_id}/reimbursement",
    response={200: LedgerEntryOut, **REFUSALS},
    summary="Cancel the reimbursement of an advance",
)
def cancel_reimbursement_of(request, entry_id: int):
    """« Annuler le remboursement »: the advance is owed again."""
    return cancel_reimbursement(get_object_or_404(LedgerEntry, pk=entry_id))


@router.post(
    "/treasury/invoices/{document_id}/expense",
    response={200: DocumentOut, 400: ErrorOut, **REFUSALS},
    summary="Record the expense of an invoice",
)
def record_invoice_expense(request, document_id: int, payload: InvoiceExpenseIn):
    """« Valider et créer l'écriture », « Marquer payée »: the expense of an
    invoice at the date it was paid, the invoice as its receipt, validated if it
    awaited review.
    """
    return create_invoice_expense(
        get_object_or_404(Document, pk=document_id), payload, request.auth
    )


@router.post(
    "/treasury/invoices/{document_id}/attach",
    response={200: DocumentOut, 400: ErrorOut, **REFUSALS},
    summary="Attach an invoice to the expense it proves",
)
def attach_invoice_to_expense(request, document_id: int, payload: InvoiceAttachIn):
    """« Ligne déjà saisie »: an invoice becomes the receipt of an expense
    entered without one, rather than an expense recorded twice.
    """
    return attach_invoice(get_object_or_404(Document, pk=document_id), payload, request.auth)
