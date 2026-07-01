from __future__ import annotations

from pathlib import Path

from xlent_scanner.detectors.filter_config import load_person_name_filters
from xlent_scanner.detectors.ner_names import looks_like_person_name
from xlent_scanner.scanner import looks_like_technical_or_academic_text, scan_text


FIXTURE = Path(__file__).parent / "fixtures" / "technical_false_positive_regression.txt"


def test_person_name_filters_are_loaded_from_data_file():
    filters = load_person_name_filters()

    assert "batch" in filters.generic_title_case_words
    assert "solver" in filters.technical_title_case_words
    assert "the" in filters.place_or_thing_preceders


def test_technical_scan_profile_rejects_extra_technical_title_case_phrases():
    assert looks_like_person_name("Sparse Solver")
    assert not looks_like_person_name("Sparse Solver", scan_profile="technical")
    assert looks_like_person_name("Neural Transformer")
    assert not looks_like_person_name("Neural Transformer", scan_profile="technical")
    assert looks_like_person_name("Thomas Elboth", scan_profile="technical")


def test_technical_regression_corpus_has_no_phone_false_positives():
    result = scan_text(FIXTURE.read_text(encoding="utf-8"), language="en", scan_profile="technical")

    assert [f.text for f in result.findings if f.category == "telefonnummer"] == []
    suppressed = {(f.category, f.text) for f in result.suppressed_findings}
    assert ("telefonnummer", "2000 3000") in suppressed
    assert ("telefonnummer", "20 25 30 35") in suppressed
    assert ("telefonnummer", "4662-4666") in suppressed


def test_technical_regression_corpus_has_no_academic_url_or_name_false_positives():
    result = scan_text(FIXTURE.read_text(encoding="utf-8"), language="en", scan_profile="technical")

    assert [f.text for f in result.findings if f.category == "nettadresse"] == []
    assert [f.text for f in result.findings if f.category.startswith("navn")] == []


def test_auto_scan_profile_detects_technical_academic_text():
    text = FIXTURE.read_text(encoding="utf-8")

    assert looks_like_technical_or_academic_text(text)
    result = scan_text(text, language="en", scan_profile="auto")

    assert result.scan_timings["scan_profile"] == "technical"
    assert [f.text for f in result.findings if f.category == "telefonnummer"] == []
    assert [f.text for f in result.findings if f.category.startswith("navn")] == []


def test_auto_scan_profile_keeps_plain_text_normal():
    result = scan_text(
        "Ring Tel: 22 34 56 78 eller +47 912 34 567.",
        language="nb",
        scan_profile="auto",
    )

    assert result.scan_timings["scan_profile"] == "normal"
    assert "22 34 56 78" in [f.text for f in result.findings if f.category == "telefonnummer"]


def test_normal_profile_still_accepts_real_phone_numbers():
    result = scan_text("Ring Tel: 22 34 56 78 eller +47 912 34 567.", language="nb")

    assert "22 34 56 78" in [f.text for f in result.findings if f.category == "telefonnummer"]
    assert "+47 912 34 567" in [f.text for f in result.findings if f.category == "telefonnummer"]
