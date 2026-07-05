from pathlib import Path

import fitz

from ib_tutor.ingest import (
    PageText,
    build_parsed_meta,
    chunk_document,
    extract_pages,
    parse_filename,
)


def test_parse_filename_standard_pp() -> None:
    fields, missing = parse_filename("mathaa_pp_2023_may_p1_hl_tz2.pdf")
    assert missing == []
    assert fields == {
        "subject": "mathaa",
        "type": "pp",
        "year": "2023",
        "session": "may",
        "paper": "p1",
        "level": "hl",
        "tz": "tz2",
    }


def test_parse_filename_standard_ms_no_tz() -> None:
    fields, missing = parse_filename("physics_ms_2022_nov_p2_sl.pdf")
    assert missing == []
    assert fields["type"] == "ms"
    assert fields["tz"] == ""


def test_parse_filename_textbook() -> None:
    fields, missing = parse_filename("mathaa_tb_oxford_ch07.pdf")
    assert missing == []
    assert fields == {
        "subject": "mathaa",
        "type": "tb",
        "publisher": "oxford",
        "chapter": "ch07",
    }


def test_parse_filename_invalid_subject_flagged() -> None:
    fields, missing = parse_filename("econ_pp_2023_may_p1_hl.pdf")
    assert "subject" in missing


def test_parse_filename_unparseable_asks_type_first() -> None:
    fields, missing = parse_filename("random_notes_v2_final.pdf")
    assert missing == ["subject", "type"]


def test_build_parsed_meta_marks_low_quality_when_prompted() -> None:
    meta = build_parsed_meta(
        {"subject": "mathaa", "type": "pp", "year": "2023", "session": "may", "paper": "p1", "level": "hl"},
        had_to_prompt=True,
    )
    assert meta.parse_quality == "low"
    assert meta.year == 2023


def test_extract_pages_markdown(tmp_path: Path) -> None:
    md = tmp_path / "notes.md"
    md.write_text("# Topic\nSome notes.")
    pages = extract_pages(md)
    assert pages == [PageText(page=1, text="# Topic\nSome notes.")]


def test_extract_pages_pdf_skips_image_only(tmp_path: Path) -> None:
    pdf_path = tmp_path / "doc.pdf"
    doc = fitz.open()
    p1 = doc.new_page()
    p1.insert_text((72, 72), "Hello world question 1")
    doc.new_page()  # blank/image-only page -> should be skipped
    doc.save(pdf_path)
    doc.close()

    pages = extract_pages(pdf_path)
    assert len(pages) == 1
    assert "Hello world" in pages[0].text


def test_chunk_document_sliding_window_respects_overlap() -> None:
    words = [f"w{i}" for i in range(1000)]
    pages = [PageText(page=1, text=" ".join(words))]
    meta = build_parsed_meta(
        {"subject": "physics", "type": "notes", "year": "2022", "session": "nov", "paper": "p2", "level": "sl"},
        had_to_prompt=False,
    )
    chunks = chunk_document(pages, meta, "physics_notes_2022_nov_p2_sl.pdf")
    assert len(chunks) == 3  # 0-512, 448-960, 896-1000
    assert chunks[0].metadata["subject"] == "physics"
    assert chunks[0].metadata["page"] == 1
    assert chunks[1].text.split()[0] == "w448"


def test_chunk_document_sliding_window_overlap_ge_size_does_not_hang() -> None:
    words = [f"w{i}" for i in range(50)]
    pages = [PageText(page=1, text=" ".join(words))]
    meta = build_parsed_meta(
        {"subject": "physics", "type": "notes", "year": "2022", "session": "nov", "paper": "p2", "level": "sl"},
        had_to_prompt=False,
    )
    chunks = chunk_document(pages, meta, "physics_notes_2022_nov_p2_sl.pdf", size=10, overlap=10)
    # step forced to 1 word when overlap >= size; completing at all proves no infinite loop
    assert len(chunks) == 41  # 50 words - 10 window + 1
    assert chunks[-1].text.split()[-1] == "w49"


def test_chunk_document_past_paper_gets_question_ids() -> None:
    text = "1. State the units of momentum.\n(a) Explain your reasoning."
    pages = [PageText(page=1, text=text)]
    meta = build_parsed_meta(
        {"subject": "physics", "type": "pp", "year": "2022", "session": "nov", "paper": "p2", "level": "sl"},
        had_to_prompt=False,
    )
    chunks = chunk_document(pages, meta, "physics_pp_2022_nov_p2_sl.pdf")
    ids = [c.metadata["question_id"] for c in chunks]
    assert ids == ["1", "1a"]
    assert all(c.metadata["parse_quality"] == "ok" for c in chunks)


def test_chunk_document_markscheme_splits_by_question_part_subpart() -> None:
    text = (
        "3. (a) M1 valid substitution\nA1 correct derivative\n"
        "(b) (i) R1 sign argument\n(ii) A1 conclusion\n"
    )
    pages = [PageText(page=1, text=text)]
    meta = build_parsed_meta(
        {"subject": "mathaa", "type": "ms", "year": "2023", "session": "may", "paper": "p1", "level": "hl"},
        had_to_prompt=False,
    )
    chunks = chunk_document(pages, meta, "mathaa_ms_2023_may_p1_hl.pdf")
    by_id = {c.metadata["question_id"]: c for c in chunks}
    # "3" and "3b" have no content of their own beyond their boundary markers
    # ("3. ", "(b) ") and are dropped rather than indexed as near-empty chunks
    assert set(by_id) == {"3a", "3bi", "3bii"}
    assert by_id["3a"].metadata["parse_quality"] == "ok"
    assert by_id["3bi"].metadata["parse_quality"] == "ok"
    assert by_id["3bii"].metadata["parse_quality"] == "ok"


def test_chunk_document_markscheme_flags_low_quality_without_mark_codes() -> None:
    text = "1. Some working with no recognisable mark codes at all"
    pages = [PageText(page=1, text=text)]
    meta = build_parsed_meta(
        {"subject": "physics", "type": "ms", "year": "2022", "session": "nov", "paper": "p2", "level": "sl"},
        had_to_prompt=False,
    )
    chunks = chunk_document(pages, meta, "physics_ms_2022_nov_p2_sl.pdf")
    assert chunks[0].metadata["parse_quality"] == "low"
