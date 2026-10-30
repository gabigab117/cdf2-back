"""Texts in French, as the API writes them to the board and the site."""

from django.utils.text import slugify

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


# slugify() drops the letters Unicode does not decompose, French ligatures among
# them ("œufs" would become "ufs"), and glues the words an apostrophe joins
# ("dautomne"): both are spelled out beforehand.
_SLUG_SPELLING = str.maketrans({"œ": "oe", "Œ": "Oe", "æ": "ae", "Æ": "Ae", "'": " ", "’": " "})


def french_slug(text: str) -> str:
    """A French text as a page address: « Chasse aux œufs d’automne » gives
    "chasse-aux-oeufs-d-automne".
    """
    return slugify(text.translate(_SLUG_SPELLING))
