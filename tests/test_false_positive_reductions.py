from xlent_scanner.deep_scanner import _filter_llm_findings_by_category_precision
from xlent_scanner.detectors.financials import find_financial_data
from xlent_scanner.detectors.keywords import find_confidential_markers
from xlent_scanner.detectors.ner_names import looks_like_person_name
from xlent_scanner.detectors.regex_en import find_us_phone
from xlent_scanner.detectors.regex_extra import find_ipv4
from xlent_scanner.detectors.regex_no import find_telefon
from xlent_scanner.detectors.regex_sv import find_telefon_sv
from xlent_scanner.detectors.secrets import detect_secrets
from xlent_scanner.scanner import scan_text


def test_classified_by_ready_is_not_confidential_marker():
    text = "the affordable system's limitations, classified by how ready the system was"

    assert list(find_confidential_markers(text)) == []


def test_classified_document_context_is_still_confidential_marker():
    text = "This is classified information and must not be distributed."

    findings = list(find_confidential_markers(text))

    assert [(f.category, f.text) for f in findings] == [
        ("konfidensielt dokument (brødtekst)", "classified information")
    ]


def test_restricted_in_normal_scientific_sentence_is_not_confidential_marker():
    text = "S-wave energy is predominantly restricted to the X and Y components."

    assert list(find_confidential_markers(text)) == []


def test_restricted_information_context_is_still_confidential_marker():
    text = "This document contains restricted information."

    findings = list(find_confidential_markers(text))

    assert [(f.category, f.text) for f in findings] == [
        ("konfidensielt dokument (brødtekst)", "restricted information")
    ]


def test_isbn_and_doi_numbers_are_not_detected_as_phone_numbers():
    text = "\n".join(
        [
            "ISBN 978-0-415-34554-1",
            "ISBN 978 0 415 34554 1",
            "DOI 10.1109/415-345-5411",
        ]
    )

    assert list(find_telefon(text)) == []
    assert list(find_us_phone(text)) == []


def test_compact_doi_suffix_is_not_detected_as_swedish_phone_number():
    text = "(doi: 10.1785/BSSA0760551393)"

    assert list(find_telefon_sv(text)) == []


def test_compact_date_is_not_detected_as_phone_number():
    assert list(find_telefon("30122025")) == []


def test_bibliographic_doi_is_not_detected_as_hourly_rate():
    text = "The reference uses DOI: 10.1002/h.12345."

    assert list(find_financial_data(text)) == []


def test_project_sum_with_norwegian_linking_word_is_detected():
    findings = list(find_financial_data("Tilbudet har en prosjektsum på 450 000 NOK."))

    assert [(finding.category, finding.text) for finding in findings] == [
        ("prosjektsum", "450 000"),
    ]


def test_specific_secret_patterns_suppress_generic_duplicates():
    github = "ghp_AbCdEfGhIjKlMnOpQrStUvWxYz1234567890Ab"
    jwt = (
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyMTIzIn0."
        "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    )

    github_findings = detect_secrets(f"Token: {github}")
    jwt_findings = detect_secrets(f"JWT: {jwt}")

    assert [finding.category for finding in github_findings] == ["GitHub Token"]
    assert [finding.category for finding in jwt_findings] == ["JWT Token"]

    repeated = detect_secrets(f"Primary: {github}\nBackup: {github}")
    assert [finding.category for finding in repeated] == ["GitHub Token", "GitHub Token"]


def test_plain_confidential_label_is_reported_once_at_highest_severity():
    result = scan_text("KONFIDENSIELT\nTilbudstekst", language="nb")
    findings = [
        finding for finding in result.findings
        if finding.category.startswith("konfidensielt dokument")
    ]

    assert [(finding.category, finding.text, finding.severity) for finding in findings] == [
        ("konfidensielt dokument (overskrift)", "KONFIDENSIELT", "rød"),
    ]


def test_ipv4_detector_skips_explicit_version_but_keeps_server_address():
    assert list(find_ipv4("Runtime version 10.20.30.40 was used.")) == []

    findings = list(find_ipv4("Version 4.2 runs on server 10.20.30.40."))
    assert [finding.text for finding in findings] == ["10.20.30.40"]


def test_technical_title_case_phrases_are_not_person_names():
    for value in [
        "Probe Interface",
        "Outer Diameter",
        "Common Format",
        "Comparison Tool",
        "Blåtind Blårens",
        "European Patent Office",
        "Claude Code",
        "Designs Python",
        "Purchase Order",
        "Unit Price",
        "Conversion Tool",
        "Frequency Range",
        "Line Total",
        "Net Amount",
        "VAT Amount",
        "Invoice Total",
        "Ocean Freight",
        "Customer Details",
    ]:
        assert not looks_like_person_name(value)


def test_real_person_names_still_pass_person_name_filter():
    for value in ["Thomas Elboth", "Jørgen Steen", "Anne-Marie Hansen"]:
        assert looks_like_person_name(value)


def test_ai_phone_postfilter_drops_bibliographic_phone_like_numbers():
    source = "DOI 10.1109/415-345-5411 describes the study."
    findings = [
        {
            "category": "Telefonnummer",
            "text": "415-345-5411",
            "context": source,
            "confidence": "high",
        }
    ]

    assert _filter_llm_findings_by_category_precision(findings, source=source) == []


def test_ai_phone_postfilter_keeps_real_phone_numbers():
    source = "Ring prosjektleder på +47 91717678 ved spørsmål."
    findings = [
        {
            "category": "Telefonnummer",
            "text": "+47 91717678",
            "context": source,
            "confidence": "high",
        }
    ]

    assert _filter_llm_findings_by_category_precision(findings, source=source) == [
        {
            "category": "Telefonnummer",
            "text": "+47 91717678",
            "context": source,
            "confidence": "high",
        }
    ]


def test_ai_bank_postfilter_drops_plain_iban_label_but_keeps_valid_iban():
    assert _filter_llm_findings_by_category_precision(
        [{"category": "IBAN", "text": "IBAN", "context": "IBAN"}],
        source="IBAN",
    ) == []

    source = "IBAN NO8010000000006"
    assert _filter_llm_findings_by_category_precision(
        [{"category": "IBAN", "text": "NO8010000000006", "context": source}],
        source=source,
    ) == [{"category": "IBAN", "text": "NO8010000000006", "context": source}]


def test_ai_address_postfilter_drops_cpu_model_strings():
    source = "Intel(R) Core(TM) i7-8700 CPU @ 3.20 GHz"
    findings = [
        {
            "category": "Fysisk adresse",
            "text": source,
            "context": source,
            "confidence": "high",
        }
    ]

    assert _filter_llm_findings_by_category_precision(findings, source=source) == []
