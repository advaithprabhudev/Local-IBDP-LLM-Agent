from ibstudy.ingest import parse_structured_text


def test_qa_blocks_do_not_swallow_trailing_term_definitions():
    text = (
        "Q: What is the law of demand?\n"
        "A: Quantity demanded falls as price rises, ceteris paribus.\n"
        "\n"
        "Q: What is the law of supply?\n"
        "A: Quantity supplied rises as price rises, ceteris paribus.\n"
        "\n"
        "Consumer surplus :: Willingness to pay minus amount paid.\n"
        "\n"
        "Producer surplus :: Amount received minus minimum acceptable price.\n"
    )
    candidates = parse_structured_text(text, "sample.md")
    fronts = {c.front for c in candidates}
    assert fronts == {
        "What is the law of demand?",
        "What is the law of supply?",
        "Consumer surplus",
        "Producer surplus",
    }
    assert len(candidates) == 4
