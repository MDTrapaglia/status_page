from app import _expand_quote_candidates


def test_expand_quote_candidates_splits_long_text_into_bounded_passages():
    long_text = " ".join([f"Sentence {i} with enough detail to be meaningful and reflective." for i in range(1, 41)])

    passages = _expand_quote_candidates([long_text], min_chars=120, max_chars=280, target_chars=220)

    assert len(passages) >= 3
    assert all(120 <= len(p) <= 280 for p in passages)
    assert passages[0].startswith("Sentence 1")


def test_expand_quote_candidates_merges_short_blocks_into_readable_capture():
    tiny_blocks = [
        "Love is the answer.",
        "Forgiveness restores peace.",
        "The miracle is a shift in perception.",
        "Choose love instead of fear.",
    ]

    passages = _expand_quote_candidates(tiny_blocks, min_chars=70, max_chars=280, target_chars=140)

    assert len(passages) >= 1
    assert all(len(p) >= 70 for p in passages)
    assert "Love is the answer." in passages[0]
