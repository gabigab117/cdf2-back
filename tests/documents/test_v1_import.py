"""The take-over of the v1's documents, on a fictitious CSV and fictitious files."""

import datetime as dt
import hashlib
from decimal import Decimal
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import CommandError, call_command

from documents.models import Document, DocumentCategory, DocumentSource, DocumentStatus
from documents.services.v1_import import CATEGORIES, COLUMNS
from tests.documents.factories import DocumentFactory
from tests.documents.samples import pdf

pytestmark = pytest.mark.django_db

HEADER = ";".join(COLUMNS)


def line(
    name,
    kind="Facture",
    issuer="Animation 60",
    number="F-0418",
    day="05/09/2025",
    amount="37,57",
    subject="Location sono",
    remark="",
    collection="Factures 2025",
):
    """A line of the CSV, in the order of its columns."""
    return ";".join([name, kind, issuer, number, day, amount, subject, remark, collection])


@pytest.fixture
def take_over(tmp_path):
    """Write a CSV of the v1 and its files, then run the import on them."""
    files = tmp_path / "v1"
    files.mkdir()

    def run(*lines, missing=(), dry_run=False, header=HEADER):
        for text in lines:
            name = text.split(";")[0]
            if name not in missing:
                (files / name).write_bytes(pdf(name))
        csv_path = tmp_path / "correspondance.csv"
        # A spreadsheet writes it in UTF-8 with its byte order mark.
        csv_path.write_text("\n".join([header, *lines]) + "\n", encoding="utf-8-sig")
        out = StringIO()
        options = {"dry_run": True} if dry_run else {}
        call_command("import_v1_documents", csv=csv_path, files=files, stdout=out, **options)
        return out.getvalue()

    return run


def stored(private_files):
    folder = Path(private_files) / "documents"
    return sorted(folder.iterdir()) if folder.exists() else []


def test_the_v1_documents_are_taken_over_validated(take_over, private_files):
    """
    Given an invoice of 37,57 € dated 5 September 2025, with a remark, and minutes
    When the v1's documents are taken over
    Then each is a validated document of the v1, its fields from the CSV
    And its note keeps the remark, the type and the collection of the v1
    """
    output = take_over(
        line("2025-09-05_Facture_Animation60_Sono_37,57EUR.pdf", remark="Payée par chèque."),
        line(
            "2025-03-14_Compte rendu_Bureau_AG.pdf",
            kind="Compte rendu",
            issuer="Bureau",
            number="",
            day="",
            amount="",
            subject="Assemblée générale",
            collection="Réunions",
        ),
    )

    invoice, minutes = Document.objects.order_by("pk")
    assert (invoice.category, invoice.status, invoice.source) == (
        DocumentCategory.INVOICE,
        DocumentStatus.VALIDATED,
        DocumentSource.V1_IMPORT,
    )
    assert (invoice.title, invoice.issuer, invoice.reference) == (
        "Location sono",
        "Animation 60",
        "F-0418",
    )
    assert (invoice.document_date, invoice.amount) == (dt.date(2025, 9, 5), Decimal("37.57"))
    assert (
        invoice.note
        == "Payée par chèque.\nRepris de la v1 : type « Facture », collection « Factures 2025 »."
    )
    assert (invoice.uploaded_by, invoice.validated_by) == (None, None)
    assert invoice.validated_at is not None
    assert (minutes.category, minutes.amount, minutes.reference, minutes.document_date) == (
        DocumentCategory.MINUTES,
        None,
        "",
        None,
    )
    assert minutes.note == "Repris de la v1 : type « Compte rendu », collection « Réunions »."
    assert len(stored(private_files)) == 2
    assert output.splitlines()[-1] == "2 documents: 2 imported, 0 imported already."


@pytest.mark.parametrize(("kind", "category"), CATEGORIES.items())
def test_each_type_of_the_v1_takes_its_category(take_over, kind, category):
    """
    Given a document of each type of the v1
    When it is taken over
    Then it takes the category the README gives that type
    """
    take_over(line("document.pdf", kind=kind))

    assert Document.objects.get().category == category


def test_a_document_imported_already_is_passed_over(take_over):
    """
    Given the import done once
    When it runs again, on the same files and one more
    Then only the new file is imported, the others passed over
    """
    first = line("2025-09-05_Facture.pdf")
    take_over(first)

    output = take_over(first, line("2025-10-01_Courrier.pdf", kind="Courrier"))

    assert Document.objects.count() == 2
    assert "Line 2: already imported, « Location sono »." in output
    assert output.splitlines()[-1] == "2 documents: 1 imported, 1 imported already."


def test_the_same_file_twice_in_the_csv_is_imported_once(take_over):
    output = take_over(line("facture.pdf"), line("facture.pdf"))

    assert Document.objects.count() == 1
    assert "Line 3: already imported" in output


def test_a_file_deposited_on_the_board_already_is_passed_over(take_over):
    """
    Given a file deposited on the board before the take-over
    When the import meets it
    Then it is passed over, not refused
    """
    DocumentFactory(sha256=hashlib.sha256(pdf("facture.pdf")).hexdigest())

    take_over(line("facture.pdf"))

    assert Document.objects.count() == 1


def test_a_dry_run_writes_nothing(take_over, private_files):
    """
    Given the v1's documents
    When the import runs dry
    Then every line is checked and reported, and nothing is written
    """
    output = take_over(line("facture.pdf"), dry_run=True)

    assert not Document.objects.exists()
    assert stored(private_files) == []
    assert "Line 2: to import, « Location sono »." in output
    assert (
        output.splitlines()[-1]
        == "1 documents: 1 to import, 0 imported already. Dry run: nothing was written."
    )


@pytest.mark.parametrize(
    ("bad", "problem"),
    [
        ({"kind": "Devis"}, "Line 3: unknown type « Devis »."),
        ({"day": "2025-09-05"}, "Line 3: invalid date « 2025-09-05 », DD/MM/YYYY expected."),
        ({"amount": "trente"}, "Line 3: invalid amount « trente »."),
        (
            {"subject": "x" * 201},
            "Line 3: Assurez-vous que cette valeur comporte au plus 200 caractères",
        ),
    ],
)
def test_an_invalid_line_fails_the_whole_import(take_over, private_files, bad, problem):
    """
    Given a valid line, then an invalid one
    When the import runs
    Then nothing is imported, and the report names the line at fault
    """
    with pytest.raises(CommandError) as caught:
        take_over(line("bon.pdf"), line("mauvais.pdf", **bad))

    assert str(caught.value).startswith(f"Nothing was imported. {problem}")
    assert not Document.objects.exists()
    assert stored(private_files) == []


def test_a_missing_file_fails_the_whole_import(take_over, tmp_path):
    with pytest.raises(CommandError) as caught:
        take_over(line("present.pdf"), line("absent.pdf"), missing=("absent.pdf",))

    assert (
        str(caught.value)
        == f"Nothing was imported. Line 3: no file « absent.pdf » in {tmp_path / 'v1'}."
    )
    assert not Document.objects.exists()


def test_a_file_of_another_type_fails_the_whole_import(take_over, tmp_path):
    """
    Given a line whose file is a web page named as a PDF
    When the import runs
    Then nothing is imported, the line and the type told
    """
    (tmp_path / "v1" / "page.pdf").write_bytes(b"<html></html>")

    with pytest.raises(CommandError) as caught:
        take_over(line("page.pdf"), missing=("page.pdf",))

    assert "Line 2: Type de fichier non accepté" in str(caught.value)


def test_a_csv_without_its_columns_is_refused(take_over):
    with pytest.raises(CommandError) as caught:
        take_over(line("facture.pdf"), header="Nom;Type")

    assert str(caught.value).startswith(
        "Nothing was imported. The CSV lacks the columns: Nouveau nom,"
    )


def test_a_failure_while_writing_leaves_no_file(take_over, private_files, monkeypatch):
    """
    Given lines all valid, the second of which fails to be written
    When the import runs
    Then nothing is imported, and the file already written is removed
    """
    save = Document.save
    calls = []

    def failing_save(self, *args, **kwargs):
        calls.append(self)
        if len(calls) == 2:
            raise RuntimeError("database unreachable")
        save(self, *args, **kwargs)

    monkeypatch.setattr(Document, "save", failing_save)

    with pytest.raises(RuntimeError):
        take_over(line("un.pdf"), line("deux.pdf"))

    assert not Document.objects.exists()
    assert stored(private_files) == []
