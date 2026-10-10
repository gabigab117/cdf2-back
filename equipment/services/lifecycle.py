"""The life of a loan (A14, A17): its checkout, its return and what it leaves
under repair, its reopening, its cancellation.

Each transition locks the loan and checks its status, then locks its
equipment, in the order of the loan's writes: a transition that takes pieces
again checks what is free, as a write does.
"""

from dataclasses import dataclass

from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.db import transaction
from django.utils import timezone

from core.text import counted
from equipment.models import Equipment, Loan, LoanBorrowerType, LoanLine, LoanStatus
from equipment.schemas import LoanReturnIn
from equipment.services.availability import Shortage, shortages
from equipment.services.loans import beyond_free, loans, lock, with_state


@dataclass(frozen=True)
class ReturnReport:
    """A loan returned, and the loans to come its damage leaves short (A17)."""

    loan: Loan
    shortages: list[Shortage]


@transaction.atomic
def check_out(loan: Loan) -> Loan:
    """Hand the equipment of a confirmed loan over: it holds it from today, even
    before its start (A15), and is refused if it is not free by then.
    """
    loan = _locked(loan)
    if loan.borrower_type == LoanBorrowerType.COMMITTEE:
        raise ValidationError(
            "Un usage comité ne sort pas : il reste confirmé jusqu’à son événement."
        )
    if loan.status != LoanStatus.CONFIRMED:
        raise ValidationError("Ce prêt n’est pas confirmé : il ne peut pas sortir.")
    lines = list(loan.lines.all())
    locked = lock({line.equipment_id for line in lines})
    loan.status = LoanStatus.OUT
    _refuse_beyond(loan, lines, locked)
    loan.save(update_fields=["status"])
    return with_state(loans().get(pk=loan.pk))


@transaction.atomic
def return_loan(loan: Loan, data: LoanReturnIn) -> ReturnReport:
    """Record how the equipment of a loan came back (A17): what is damaged goes
    under repair, within the total, with a mention in its note; what is missing
    is reported, the stock left as it is. The loans to come that the repairs
    leave short are named.
    """
    loan = _locked(loan)
    if loan.status != LoanStatus.OUT:
        raise ValidationError("Ce prêt n’est pas sorti : il ne peut pas être rendu.")
    lines = {line.pk: line for line in loan.lines.all()}
    _count_back(lines, data)
    locked = lock({line.equipment_id for line in lines.values()})
    repaired: list[Equipment] = []
    for line in lines.values():
        line.save(update_fields=["damaged_quantity", "missing_quantity"])
        if line.damaged_quantity:
            equipment = locked[line.equipment_id]
            equipment.repair_quantity = min(
                equipment.repair_quantity + line.damaged_quantity, equipment.total_quantity
            )
            equipment.repair_note = _with_mention(equipment.repair_note, _mention(loan, line))
            equipment.save(update_fields=["repair_quantity", "repair_note"])
            repaired.append(equipment)
    loan.status = LoanStatus.RETURNED
    loan.returned_at = timezone.now()
    loan.save(update_fields=["status", "returned_at"])
    return ReturnReport(with_state(loans().get(pk=loan.pk)), shortages(repaired))


@transaction.atomic
def reopen(loan: Loan) -> Loan:
    """Undo the return of a loan, as the v1 did: what it put under repair comes
    out of it, never below none, and its mention leaves the note if it is still
    there. The loan holds its pieces again: it is refused if they are not free.
    """
    loan = _locked(loan)
    if loan.status != LoanStatus.RETURNED:
        raise ValidationError("Ce prêt n’est pas rendu : il ne peut pas être rouvert.")
    lines = list(loan.lines.all())
    locked = lock({line.equipment_id for line in lines})
    for line in lines:
        if line.damaged_quantity:
            equipment = locked[line.equipment_id]
            equipment.repair_quantity = max(equipment.repair_quantity - line.damaged_quantity, 0)
            equipment.repair_note = _without_mention(equipment.repair_note, _mention(loan, line))
            equipment.save(update_fields=["repair_quantity", "repair_note"])
        line.damaged_quantity = line.missing_quantity = 0
        line.save(update_fields=["damaged_quantity", "missing_quantity"])
    loan.status = LoanStatus.OUT
    loan.returned_at = None
    _refuse_beyond(loan, lines, locked)
    loan.save(update_fields=["status", "returned_at"])
    return with_state(loans().get(pk=loan.pk))


@transaction.atomic
def cancel(loan: Loan) -> Loan:
    """Cancel a confirmed loan, the committee's included: its equipment is free again."""
    loan = _locked(loan)
    if loan.status != LoanStatus.CONFIRMED:
        raise ValidationError("Seul un prêt confirmé s’annule : un prêt sorti se rend.")
    loan.status = LoanStatus.CANCELLED
    loan.save(update_fields=["status"])
    return with_state(loans().get(pk=loan.pk))


def _locked(loan: Loan) -> Loan:
    return Loan.objects.select_for_update().get(pk=loan.pk)


def _count_back(lines: dict[int, LoanLine], data: LoanReturnIn) -> None:
    """Set what came back of each line given, every error at once, a line's
    under its position: "lines.1.damaged_quantity". A line not given came back
    whole.
    """
    errors: dict[str, list[str]] = {}
    seen: set[int] = set()
    for index, back in enumerate(data.lines):
        line = lines.get(back.line)
        if line is None or back.line in seen:
            errors[f"lines.{index}.line"] = [
                "Cette ligne n’appartient pas au prêt, ou figure deux fois."
            ]
            continue
        seen.add(back.line)
        line.damaged_quantity = back.damaged_quantity
        line.missing_quantity = back.missing_quantity
        try:
            line.full_clean(exclude={"loan", "equipment"})
        except ValidationError as error:
            for field, messages in error.message_dict.items():
                place = "" if field == NON_FIELD_ERRORS else f".{field}"
                errors[f"lines.{index}{place}"] = messages
    if errors:
        raise ValidationError(errors)


def _refuse_beyond(loan: Loan, lines: list[LoanLine], locked: dict[int, Equipment]) -> None:
    beyond = beyond_free(loan, lines, locked)
    if beyond:
        raise ValidationError(
            ["Le matériel de ce prêt n’est pas libre sur ses jours :", *beyond.values()]
        )


def _mention(loan: Loan, line: LoanLine) -> str:
    """« 1 abîmé au retour du prêt P-2026-018. », in the repair note (A17)."""
    damaged = counted(line.damaged_quantity, "abîmé", "abîmés")
    return f"{damaged} au retour du prêt {loan.number}."


def _with_mention(note: str, mention: str) -> str:
    return f"{note}\n{mention}" if note else mention


def _without_mention(note: str, mention: str) -> str:
    """The note without the mention, if it is still there: the board may have
    rewritten it since.
    """
    lines = note.split("\n")
    if mention in lines:
        lines.remove(mention)
    return "\n".join(lines)
