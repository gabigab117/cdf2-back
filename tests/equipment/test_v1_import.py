"""The take-over of the v1's inventory, on a fictitious export and a fictitious sheet."""

import json
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from equipment.models import Equipment, EquipmentCategory
from equipment.services.v1_import import COLUMNS
from tests.equipment.factories import EquipmentFactory

pytestmark = pytest.mark.django_db

HEADER = ";".join(COLUMNS)

# Three equipment of the v1, as its export lists them.
EQUIPMENT = [
    {"name": "Tables pliantes 180 cm", "stock_quantity": 24},
    {"name": "Barnums 3 × 3 m", "stock_quantity": 4},
    {"name": "Percolateurs 100 tasses", "stock_quantity": 2},
]

SHEET = [
    "Tables pliantes 180 cm;Mobilier;Local du comité · rack A;60",
    "barnums 3 × 3 m ;Barnums;Garage communal;1 250,50",
    "Percolateurs 100 tasses;Cuisine;;",
]


@pytest.fixture
def take_over(tmp_path):
    """Write an export of the v1 and a mapping sheet, then run the import on them."""

    def run(export=None, sheet=SHEET, *, header=HEADER, dry_run=False):
        inventory = tmp_path / "inventaire_materiel.json"
        content = {"equipment": EQUIPMENT, "open_loans": []} if export is None else export
        inventory.write_text(json.dumps(content), encoding="utf-8")
        mapping = tmp_path / "fiche_de_reprise.csv"
        # A spreadsheet writes it in UTF-8 with its byte order mark.
        mapping.write_text("\n".join([header, *sheet]) + "\n", encoding="utf-8-sig")
        out = StringIO()
        options = {"dry_run": True} if dry_run else {}
        call_command(
            "import_v1_equipment", inventory=inventory, mapping=mapping, stdout=out, **options
        )
        return out.getvalue()

    return run


def test_the_inventory_of_the_v1_is_taken_over_with_its_sheet(take_over):
    """
    Given an export of three equipment of the v1, and the sheet that maps them
    When it is imported
    Then each equipment takes its stock from the export, its category, place
    and value from the sheet, none under repair, and the report counts them
    """
    report = take_over()

    tables, marquees, percolators = Equipment.objects.order_by("pk")
    assert (tables.name, tables.category, tables.storage_location, tables.unit_value) == (
        "Tables pliantes 180 cm",
        EquipmentCategory.FURNITURE,
        "Local du comité · rack A",
        Decimal(60),
    )
    assert (marquees.name, marquees.total_quantity, marquees.repair_quantity) == (
        "Barnums 3 × 3 m",
        4,
        0,
    )
    assert marquees.unit_value == Decimal("1250.50")
    assert (percolators.category, percolators.storage_location, percolators.unit_value) == (
        EquipmentCategory.KITCHEN,
        "",
        None,
    )
    assert report.splitlines() == [
        "« Tables pliantes 180 cm », 24 pieces: imported.",
        "« Barnums 3 × 3 m », 4 pieces: imported.",
        "« Percolateurs 100 tasses », 2 pieces: imported.",
        "3 equipment items, 30 units: 3 imported, 0 existing already.",
    ]


def test_an_equipment_whose_name_exists_is_passed_over(take_over):
    """
    Given marquees in the inventory already, under another case
    When the export is imported, twice
    Then the marquees are passed over, and the second import imports nothing
    """
    EquipmentFactory(name="BARNUMS 3 × 3 M")

    first = take_over()
    second = take_over()

    assert Equipment.objects.count() == 3
    assert "« Barnums 3 × 3 m », 4 pieces: exists already." in first
    assert second.splitlines()[-1] == "3 equipment items, 30 units: 0 imported, 3 existing already."


def test_a_dry_run_checks_everything_and_writes_nothing(take_over):
    """
    Given an export and its sheet
    When a dry run imports them
    Then the report tells what would be imported, and nothing is written
    """
    report = take_over(dry_run=True)

    assert not Equipment.objects.exists()
    assert report.splitlines()[0] == "« Tables pliantes 180 cm », 24 pieces: to import."
    assert report.splitlines()[-1] == (
        "3 equipment items, 30 units: 3 to import, 0 existing already. "
        "Dry run: nothing was written."
    )


def with_equipment(*items, open_loans=()):
    return {"equipment": list(items), "open_loans": list(open_loans)}


@pytest.mark.parametrize(
    ("export", "sheet", "problem"),
    [
        (
            with_equipment(*EQUIPMENT, open_loans=[{"borrower": "Club de football"}]),
            SHEET,
            "The v1 still has 1 open loans: close them before the take-over.",
        ),
        ({"equipment": EQUIPMENT}, SHEET, "The inventory tells no « open_loans » list."),
        (
            {"items": EQUIPMENT, "open_loans": []},
            SHEET,
            "The inventory holds no « equipment » list.",
        ),
        (["not", "an", "export"], SHEET, "The inventory holds no « equipment » list."),
        (with_equipment({"stock_quantity": 2}), SHEET, "Equipment 1: no name."),
        (with_equipment("Bancs"), SHEET, "Equipment 1: no name."),
        (
            with_equipment({"name": "Bancs", "stock_quantity": -1}),
            SHEET,
            "Equipment 1: invalid stock « -1 » for « Bancs ».",
        ),
        (
            with_equipment({"name": "Bancs", "stock_quantity": True}),
            SHEET,
            "Equipment 1: invalid stock « True » for « Bancs ».",
        ),
        (
            with_equipment(EQUIPMENT[0], {"name": "TABLES PLIANTES 180 CM", "stock_quantity": 2}),
            SHEET,
            "Equipment 2: « TABLES PLIANTES 180 CM » is listed twice.",
        ),
        (
            None,
            [*SHEET, "Tentes;Barnums;;"],
            "Mapping line 5: no equipment of the inventory is named « Tentes ».",
        ),
        (None, SHEET[:2], "« Percolateurs 100 tasses » is missing from the mapping sheet."),
        (
            None,
            [*SHEET[:2], "Percolateurs 100 tasses;Vaisselle;;"],
            "Mapping line 4: unknown category « Vaisselle ».",
        ),
        (
            None,
            [*SHEET[:2], "Percolateurs 100 tasses;Cuisine;;quatre-vingt-dix"],
            "Mapping line 4: invalid value « quatre-vingt-dix ».",
        ),
        (
            None,
            [*SHEET, "Percolateurs 100 tasses;Cuisine;;90"],
            "Mapping line 5: « Percolateurs 100 tasses » is mapped twice.",
        ),
        (
            with_equipment({"name": "B" * 121, "stock_quantity": 2}),
            [f"{'B' * 121};Barnums;;"],
            f"« {'B' * 121} »: Assurez-vous que cette valeur comporte au plus 120 caractères "
            "(actuellement 121).",
        ),
    ],
)
def test_an_inventory_or_a_sheet_out_of_rule_imports_nothing(take_over, export, sheet, problem):
    """
    Given an export with loans still open, without its lists, an equipment
    without a name, a valid stock or twice listed; or a sheet that maps an
    equipment the export lacks, lacks one, gives an unknown category or an
    invalid value, maps one twice, or gives a name too long
    When it is imported
    Then nothing is imported, and the command names the problem
    """
    with pytest.raises(CommandError) as error:
        take_over(export, sheet)

    assert str(error.value) == f"Nothing was imported. {problem}"
    assert not Equipment.objects.exists()


def test_a_sheet_without_its_columns_imports_nothing(take_over):
    """
    Given a sheet that lacks the column of the values
    When it is imported
    Then nothing is imported, and the command names the column
    """
    with pytest.raises(CommandError) as error:
        take_over(header="Nom;Catégorie;Rangement")

    assert (
        str(error.value)
        == "Nothing was imported. The mapping sheet lacks the columns: Valeur unitaire."
    )


def test_an_export_that_cannot_be_read_imports_nothing(tmp_path):
    """
    Given an export that is no JSON
    When it is imported
    Then nothing is imported, and the command tells it cannot read it
    """
    inventory = tmp_path / "inventaire_materiel.json"
    inventory.write_text("{not json", encoding="utf-8")
    mapping = tmp_path / "fiche_de_reprise.csv"
    mapping.write_text(HEADER + "\n", encoding="utf-8-sig")

    with pytest.raises(CommandError) as error:
        call_command("import_v1_equipment", inventory=inventory, mapping=mapping, stdout=StringIO())

    assert str(error.value).startswith("Nothing was imported. The inventory cannot be read:")
