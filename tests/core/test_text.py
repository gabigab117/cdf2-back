import pytest

from core.text import counted


@pytest.mark.parametrize(("count", "text"), [(0, "0 libre"), (1, "1 libre"), (2, "2 libres")])
def test_a_count_takes_the_singular_below_two(count, text):
    """
    Given none, one or two pieces free
    When their count is written
    Then French takes the singular for none and one, the plural from two
    """
    assert counted(count, "libre", "libres") == text
