"""The take-over of the v1's documents (A1), run once, in production (card 10.6).

The v1's documents were renamed and listed in a CSV file: one line a
document, with its type, issuer, number, date, amount and subject, a remark,
and the collection it belonged to. Each becomes a validated document of the
board, never handed to the assistant (phase 9).

The import is all or nothing: every line is read and checked first, then
every document written in a single transaction, and the files already written
are removed if any write fails. A file imported already is passed over, so
that the import runs again after an addition to the CSV.
"""

import csv
import datetime as dt
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.files.base import File
from django.db import transaction
from django.utils import timezone

from documents.models import Document, DocumentCategory, DocumentSource, DocumentStatus
from documents.services.files import StoredFile, read_upload

# The columns of the CSV, by what they hold.
FILE = "Nouveau nom"
TYPE = "Type"
ISSUER = "Émetteur"
REFERENCE = "Numéro"
DATE = "Date"
AMOUNT = "Montant TTC"
SUBJECT = "Objet"
REMARK = "Remarque"
COLLECTION = "Collection"
COLUMNS = (FILE, TYPE, ISSUER, REFERENCE, DATE, AMOUNT, SUBJECT, REMARK, COLLECTION)

# The category of each type of the v1 (the README's table).
CATEGORIES = {
    "Facture": DocumentCategory.INVOICE,
    "Ticket de caisse": DocumentCategory.INVOICE,
    "Bon de commande": DocumentCategory.ORDER,
    "Compte rendu": DocumentCategory.MINUTES,
    "Liste de courses": DocumentCategory.MISC,
    "Convocation": DocumentCategory.MISC,
    "Courrier": DocumentCategory.MISC,
    "Relevé bancaire": DocumentCategory.MISC,
    "Modèle": DocumentCategory.MISC,
    "Convention de prêt": DocumentCategory.MISC,
    "Flyer": DocumentCategory.MISC,
    "Formulaire": DocumentCategory.MISC,
    "Règlement": DocumentCategory.MISC,
}


class V1ImportError(Exception):
    """A line of the CSV, or the CSV itself, the import cannot take: nothing is written."""


@dataclass(frozen=True)
class ImportLine:
    """A line of the CSV, read: the document it makes, or the one it repeats."""

    number: int
    title: str
    # None: the file is imported already.
    document: Document | None
    stored: StoredFile | None


def import_v1_documents(csv_path: Path, files: Path, *, dry_run: bool) -> list[ImportLine]:
    """Take over the documents the CSV lists, their files in a folder.

    Returns the lines read, those imported and those passed over; a dry run
    checks them all and writes nothing.
    """
    lines = _read(csv_path, files)
    if not dry_run:
        _write([line for line in lines if line.document is not None])
    return lines


def _read(csv_path: Path, files: Path) -> list[ImportLine]:
    # The CSV is written by a spreadsheet, in UTF-8 with its byte order mark.
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        missing = [column for column in COLUMNS if column not in (reader.fieldnames or [])]
        if missing:
            raise V1ImportError(f"The CSV lacks the columns: {', '.join(missing)}.")
        known = set(Document.objects.values_list("sha256", flat=True))
        lines = []
        for row in reader:
            line = _line(reader.line_num, row, files, known)
            if line.stored is not None:
                known.add(line.stored.sha256)
            lines.append(line)
    return lines


def _line(number: int, row: dict[str, str], files: Path, known: set[str]) -> ImportLine:
    path = files / row[FILE]
    if not path.is_file():
        raise _error(number, f"no file « {row[FILE]} » in {files}.")
    category = CATEGORIES.get(row[TYPE])
    if category is None:
        raise _error(number, f"unknown type « {row[TYPE]} ».")
    with path.open("rb") as file:
        try:
            stored = read_upload(File(file, name=path.name))
        except ValidationError as error:
            raise _error(number, " ".join(error.messages)) from error
    title = row[SUBJECT] or path.stem
    if stored.sha256 in known:
        return ImportLine(number, title, None, None)
    document = Document(
        category=category,
        status=DocumentStatus.VALIDATED,
        source=DocumentSource.V1_IMPORT,
        title=title,
        issuer=row[ISSUER],
        reference=row[REFERENCE],
        document_date=_date(number, row[DATE]),
        amount=_amount(number, row[AMOUNT]),
        note=_note(row),
        original_name=stored.name,
        mime_type=stored.mime_type,
        size=stored.size,
        sha256=stored.sha256,
        validated_at=timezone.now(),
    )
    try:
        document.full_clean(exclude={"file"})
    except ValidationError as error:
        raise _error(number, " ".join(error.messages)) from error
    return ImportLine(number, title, document, stored)


def _error(number: int, problem: str) -> V1ImportError:
    return V1ImportError(f"Line {number}: {problem}")


def _date(number: int, text: str) -> dt.date | None:
    if not text:
        return None
    try:
        return dt.datetime.strptime(text, "%d/%m/%Y").date()
    except ValueError as error:
        raise _error(number, f"invalid date « {text} », DD/MM/YYYY expected.") from error


def _amount(number: int, text: str) -> Decimal | None:
    # « 37,57 », or « 1 234,56 » with a space of any kind between thousands.
    amount = "".join(text.split()).replace(",", ".")
    if not amount:
        return None
    try:
        return Decimal(amount)
    except InvalidOperation as error:
        raise _error(number, f"invalid amount « {text} ».") from error


def _note(row: dict[str, str]) -> str:
    # The remark of the v1, then where the document came from: its type and its
    # collection, which no field of the v2 keeps.
    origin = f"Repris de la v1 : type « {row[TYPE]} », collection « {row[COLLECTION]} »."
    return f"{row[REMARK]}\n{origin}" if row[REMARK] else origin


def _write(lines: list[ImportLine]) -> None:
    written: list[Document] = []
    try:
        with transaction.atomic():
            for line in lines:
                line.document.file.save(line.stored.name, line.stored.content, save=False)
                written.append(line.document)
                line.document.save()
    except BaseException:
        for document in written:
            document.file.delete(save=False)
        raise
