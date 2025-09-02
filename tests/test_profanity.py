from cogs.watchers.profanity_watch import build_word_pattern, soft_censor_text


def test_censor_basic():
    pat = build_word_pattern(["kurva"])
    text, cnt = soft_censor_text("te kurva", pat)
    assert cnt == 1
    assert "k***a" in text


def test_leet_variant():
    pat = build_word_pattern(["geci"])
    text, cnt = soft_censor_text("g3ci", pat)
    assert cnt == 1
    assert "g**i" in text
