"""Texts in French, as the API writes them to the board."""


def counted(count: int, one: str, many: str) -> str:
    """« 0 libre », « 1 libre », « 2 libres »: French takes the singular below two.

    Django's ngettext follows the plural rule of its translation catalog. The
    project's own messages have none: it falls back to English's, which writes
    « 0 libres ».
    """
    return f"{count} {one if count < 2 else many}"
