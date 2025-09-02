import sys, pathlib
sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from cogs.utils.text import shorten, no_repeat


def test_shorten_truncates_with_ellipsis():
    s = "  This   is  a    very long text  "
    out = shorten(s, limit=10)
    assert out.endswith("…")
    assert len(out) == 10
    assert out.startswith("This")


def test_no_repeat_collapses_characters_and_words():
    assert no_repeat("loooooool") == "loool"
    assert no_repeat("spam spam Spam eggs") == "spam eggs"
