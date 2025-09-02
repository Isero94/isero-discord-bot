import sys, pathlib
sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from cogs.utils.text import shorten, no_repeat, chunk_message, truncate_by_chars


def test_shorten_truncates_with_ellipsis():
    s = "  This   is  a    very long text  "
    out = shorten(s, limit=10)
    assert out.endswith("…")
    assert len(out) == 10
    assert out.startswith("This")


def test_no_repeat_collapses_characters_and_words():
    assert no_repeat("loooooool") == "loool"
    assert no_repeat("spam spam Spam eggs") == "spam eggs"


def test_chunk_message_splits_with_prefix():
    text = "a" * 650
    chunks = chunk_message(text, limit=300)
    assert len(chunks) == 3
    assert chunks[0].startswith("(1/3) ")
    assert all(len(c) <= 300 for c in chunks)


def test_truncate_by_chars():
    assert truncate_by_chars("hello world", 5) == "hell…"
    assert truncate_by_chars("short", 10) == "short"
