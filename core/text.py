"""Texts in French, as the API writes them to the board."""

# The association's name, as its calendar and its documents print it.
COMMITTEE = "Comité des fêtes d’Ons-en-Bray"

# What the purge of personal data writes in place of a name (A9). A loan to a
# third party, a reservation and a volunteer each need one, and the board's
# lists, their accessible labels and the reservations' workbook still read.
ERASED_NAME = "Nom effacé"


def count_text(count: int, one: str, many: str) -> str:
    """« 0 libre », « 1 libre », « 2 libres »: French takes the singular below two.

    Django's ngettext follows the plural rule of its translation catalog. The
    project's own messages have none: it falls back to English's, which writes
    « 0 libres ».
    """
    return f"{count} {one if count < 2 else many}"
