"""The take-over of the v1's inventory (A1), run once, in production (card 10.6).

The v1 exported its equipment to JSON: each with its name and its pieces in
stock, with the loans still open, which must be none at the switch. The v1 knew
no category, place nor value: a mapping sheet, filled in with the board before
the take-over, gives them, a line an equipment, by its name.

The import is all or nothing: the inventory and the sheet are read and checked
first, then every equipment written in a single transaction. An equipment whose
name exists already is passed over, so that the import runs again after a fix.
"""

import csv
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.core.exceptions import ValidationError
from django.db import transaction

from equipment.models import Equipment, EquipmentCategory

# The keys of the v1's export, as the roadmap describes it: checked against the
# real file before the take-over (card 10.6).
EQUIPMENT_KEY = "equipment"
NAME_KEY = "name"
STOCK_KEY = "stock_quantity"
OPEN_LOANS_KEY = "open_loans"

# The columns of the mapping sheet.
NAME = "Nom"
CATEGORY = "Catégorie"
PLACE = "Rangement"
VALUE = "Valeur unitaire"
COLUMNS = (NAME, CATEGORY, PLACE, VALUE)

# A category of the sheet by its label, as the inventory's chips write it.
CATEGORIES = {label: value for value, label in EquipmentCategory.choices}


class V1ImportError(Exception):
    """An inventory or a mapping sheet the import cannot take: nothing is written."""


@dataclass(frozen=True)
class MappingLine:
    """What the sheet gives an equipment of the v1."""

    number: int
    name: str
    category: str
    place: str
    value: Decimal | None


@dataclass(frozen=True)
class ImportLine:
    """An equipment of the v1, read: the one it makes, or none when its name exists."""

    name: str
    quantity: int
    equipment: Equipment | None


def import_v1_equipment(inventory: Path, mapping: Path, *, dry_run: bool) -> list[ImportLine]:
    """Take over the equipment of the v1's export, as the mapping sheet completes it.

    Returns the equipment read, those imported and those passed over; a dry run
    checks them all and writes nothing.
    """
    lines = _match(_inventory(inventory), _mapping(mapping))
    if not dry_run:
        _write([line.equipment for line in lines if line.equipment is not None])
    return lines


def _inventory(path: Path) -> list[tuple[str, int]]:
    """The equipment of the export, by name and pieces in stock."""
    try:
        export = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise V1ImportError(f"The inventory cannot be read: {error}.") from error
    if not isinstance(export, dict) or not isinstance(export.get(EQUIPMENT_KEY), list):
        raise V1ImportError(f"The inventory holds no « {EQUIPMENT_KEY} » list.")
    open_loans = export.get(OPEN_LOANS_KEY)
    if not isinstance(open_loans, list):
        raise V1ImportError(f"The inventory tells no « {OPEN_LOANS_KEY} » list.")
    if open_loans:
        raise V1ImportError(
            f"The v1 still has {len(open_loans)} open loans: close them before the take-over."
        )
    items: list[tuple[str, int]] = []
    seen: set[str] = set()
    for number, entry in enumerate(export[EQUIPMENT_KEY], start=1):
        name, quantity = _item(number, entry)
        if name.casefold() in seen:
            raise V1ImportError(f"Equipment {number}: « {name} » is listed twice.")
        seen.add(name.casefold())
        items.append((name, quantity))
    return items


def _item(number: int, entry: object) -> tuple[str, int]:
    name = entry.get(NAME_KEY) if isinstance(entry, dict) else None
    if not isinstance(name, str) or not name.strip():
        raise V1ImportError(f"Equipment {number}: no name.")
    quantity = entry.get(STOCK_KEY)
    # A boolean is an int to Python: it is no count of pieces.
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 0:
        raise V1ImportError(f"Equipment {number}: invalid stock « {quantity} » for « {name} ».")
    return name.strip(), quantity


def _mapping(path: Path) -> dict[str, MappingLine]:
    """The lines of the sheet, by the name of their equipment, its case aside."""
    # The sheet is written by a spreadsheet, in UTF-8 with its byte order mark.
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        missing = [column for column in COLUMNS if column not in (reader.fieldnames or [])]
        if missing:
            raise V1ImportError(f"The mapping sheet lacks the columns: {', '.join(missing)}.")
        sheet: dict[str, MappingLine] = {}
        for row in reader:
            line = _mapping_line(reader.line_num, row)
            if line.name.casefold() in sheet:
                raise _error(line.number, f"« {line.name} » is mapped twice.")
            sheet[line.name.casefold()] = line
    return sheet


def _mapping_line(number: int, row: dict[str, str]) -> MappingLine:
    category = CATEGORIES.get(row[CATEGORY].strip())
    if category is None:
        raise _error(number, f"unknown category « {row[CATEGORY]} ».")
    return MappingLine(
        number, row[NAME].strip(), category, row[PLACE].strip(), _value(number, row[VALUE])
    )


def _value(number: int, text: str) -> Decimal | None:
    # « 60 », « 60,00 », or « 1 250,00 » with a space of any kind between thousands.
    value = "".join(text.split()).replace(",", ".")
    if not value:
        return None
    try:
        return Decimal(value)
    except InvalidOperation as error:
        raise _error(number, f"invalid value « {text} ».") from error


def _error(number: int, problem: str) -> V1ImportError:
    return V1ImportError(f"Mapping line {number}: {problem}")


def _match(items: list[tuple[str, int]], sheet: dict[str, MappingLine]) -> list[ImportLine]:
    """Each equipment of the export with its line of the sheet, which maps none other."""
    names = {name.casefold() for name, _quantity in items}
    for key, line in sheet.items():
        if key not in names:
            raise _error(line.number, f"no equipment of the inventory is named « {line.name} ».")
    existing = {name.casefold() for name in Equipment.objects.values_list("name", flat=True)}
    lines = []
    for name, quantity in items:
        line = sheet.get(name.casefold())
        if line is None:
            raise V1ImportError(f"« {name} » is missing from the mapping sheet.")
        if name.casefold() in existing:
            lines.append(ImportLine(name, quantity, None))
            continue
        equipment = Equipment(
            name=name,
            category=line.category,
            storage_location=line.place,
            total_quantity=quantity,
            unit_value=line.value,
        )
        try:
            equipment.full_clean()
        except ValidationError as error:
            raise V1ImportError(f"« {name} »: {' '.join(error.messages)}") from error
        lines.append(ImportLine(name, quantity, equipment))
    return lines


@transaction.atomic
def _write(equipment: list[Equipment]) -> None:
    Equipment.objects.bulk_create(equipment)
