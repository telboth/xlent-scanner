from xlent_scanner.detectors.regex_extra import (
    detect_extra,
    find_bank_routing_details,
    find_child_school_data,
    find_confidential_label_lines,
    find_document_metadata_fields,
    find_hr_personnel_data,
    find_tax_id,
    find_legal_case_data,
    find_labeled_phone_or_fax,
    find_location_device_ids,
    find_medical_fields,
    find_po_box_address,
    find_street_address,
    find_swift,
)
from xlent_scanner.scanner import scan_text


def test_horten_is_not_detected_as_swift_bic() -> None:
    samples = [
        "Omfanget av overføringsverdi fra Horten er altså avhengig av at kommunene...",
        "Hortens digitaliseringsansvarlige formulerte problemet konkret i intervjuet:",
        "Omfanget av OVERFØRINGSVERDI fra HORTENXX er altså avhengig.",
    ]

    for text in samples:
        assert list(find_swift(text)) == []


def test_swift_bic_requires_valid_country_code() -> None:
    assert list(find_swift("SWIFT/BIC: HORTENXX")) == []


def test_valid_swift_bic_is_still_detected() -> None:
    findings = list(find_swift("SWIFT/BIC: DNBANOKK"))

    assert len(findings) == 1
    assert findings[0].category == "SWIFT/BIC-kode"
    assert findings[0].text == "DNBANOKK"


def test_labeled_tel_and_fax_numbers_are_detected() -> None:
    text = (
        "Tel: 2025461,Fax: 09-2025494 "
        "VWServiceCentre-Dubai Tel: 04-7041111,Fax: 04-7053430 Audi Service"
    )

    findings = list(find_labeled_phone_or_fax(text))

    assert [(f.category, f.text) for f in findings] == [
        ("telefonnummer", "2025461"),
        ("telefonnummer", "09-2025494"),
        ("telefonnummer", "04-7041111"),
        ("telefonnummer", "04-7053430"),
    ]


def test_unlabeled_short_numbers_are_not_detected_as_labeled_phone() -> None:
    assert list(find_labeled_phone_or_fax("Order 2025461 and invoice 7041111")) == []


def test_po_box_address_is_detected() -> None:
    text = "Audl Volkswagen Middle East ° PO Box 27758 * Dubai - United Arab Emirates"

    findings = list(find_po_box_address(text))

    assert [(f.category, f.text) for f in findings] == [
        ("fysisk adresse", "PO Box 27758 * Dubai - United Arab Emirates")
    ]


def test_po_box_without_number_is_not_detected() -> None:
    assert list(find_po_box_address("Send this to the PO Box office later.")) == []


def test_detect_extra_includes_po_box_address() -> None:
    text = "Audl Volkswagen Middle East ° PO Box 27758 * Dubai - United Arab Emirates"

    findings = detect_extra(text)

    assert any(
        f.category == "fysisk adresse"
        and f.text == "PO Box 27758 * Dubai - United Arab Emirates"
        for f in findings
    )


def test_tax_id_after_label_is_detected_as_person_id() -> None:
    samples = [
        "Tax ID: 123-45-6789",
        "Tax Id: 996-90-5190",
        "Tax Id 987654321",
        "tax identification number: AB-123456789",
        "TIN: 12 345 678",
        "SSN: 123-45-6789",
        "Passport No: PA1234567",
        "Driver License: D1234567",
    ]

    findings = [finding for sample in samples for finding in find_tax_id(sample)]

    assert [(f.category, f.text) for f in findings] == [
        ("tax identification number", "123-45-6789"),
        ("tax identification number", "996-90-5190"),
        ("tax identification number", "987654321"),
        ("tax identification number", "AB-123456789"),
        ("tax identification number", "12 345 678"),
        ("tax identification number", "123-45-6789"),
        ("tax identification number", "PA1234567"),
        ("tax identification number", "D1234567"),
    ]


def test_tax_id_requires_explicit_label() -> None:
    assert list(find_tax_id("Invoice 123-45-6789 is not a tax id label.")) == []


def test_street_addresses_are_detected_across_languages() -> None:
    text = "\n".join(
        [
            "Besøksadresse: Storgata 10, 0155 Oslo.",
            "Office: Baker Street 221B.",
            "Government office: 10 Downing Street.",
            "DE: Hauptstraße 5.",
            "FR: Rue de Rivoli 99.",
            "ES: Calle Mayor 12.",
            "US: 8041 Hawkins Village Suite 621.",
        ]
    )

    findings = list(find_street_address(text))

    assert [(f.category, f.text) for f in findings] == [
        ("fysisk adresse", "Storgata 10, 0155 Oslo"),
        ("fysisk adresse", "Baker Street 221B"),
        ("fysisk adresse", "10 Downing Street"),
        ("fysisk adresse", "Hauptstraße 5"),
        ("fysisk adresse", "Rue de Rivoli 99"),
        ("fysisk adresse", "Calle Mayor 12"),
        ("fysisk adresse", "8041 Hawkins Village Suite 621"),
    ]


def test_street_address_requires_address_word_and_house_number() -> None:
    samples = [
        "Frequency Range 10",
        "Unit Price 10",
        "Baker Street",
        "Chapter 10 explains street naming.",
    ]

    for sample in samples:
        assert list(find_street_address(sample)) == []


def test_detect_extra_includes_street_address() -> None:
    findings = detect_extra("Ship to Baker Street 221B.")

    assert any(f.category == "fysisk adresse" and f.text == "Baker Street 221B" for f in findings)


def test_hr_personnel_fields_are_detected_with_explicit_labels() -> None:
    text = "Annual salary: NOK 850 000. Sick leave: 40% from January. Termination: 2026-02-01."

    findings = list(find_hr_personnel_data(text))

    assert ("lønn", "850 000") in [(f.category, f.text) for f in findings]
    assert ("personalsak", "40% from January") in [(f.category, f.text) for f in findings]
    assert ("personalsak", "2026-02-01") in [(f.category, f.text) for f in findings]


def test_legal_case_fields_are_detected_with_explicit_context() -> None:
    text = "Court case: HR-2026-001. Police report: OSLO/12345."

    findings = list(find_legal_case_data(text))

    assert [(f.category, f.text) for f in findings] == [
        ("juridisk forhold", "HR-2026-001"),
        ("juridisk forhold", "OSLO/12345"),
    ]


def test_child_school_fields_are_detected_with_explicit_context() -> None:
    text = "Student: Kari Nordmann. Class: 5B. Guardian: Ola Nordmann."

    findings = list(find_child_school_data(text))

    assert [(f.category, f.text) for f in findings] == [
        ("barn/elevopplysning", "Kari Nordmann"),
        ("barn/elevopplysning", "5B"),
        ("barn/elevopplysning", "Ola Nordmann"),
    ]


def test_hr_legal_and_child_school_regex_reject_academic_running_text() -> None:
    samples = [
        "Conference on Environmental and Engineering Geophysics, IOP Publishing, 012054. (doi:10.1088/1742-6596/2651/1/012054).",
        "The load is a matching termination to the line’s characteristic impedance.",
        "An ideal −1 termination reduces to log-of-unity.",
        "Further investigation showed that the device was more capable than expected.",
        "There was no further investigation into the lower limit.",
        "TABLE 3.6: Inputs and algorithm class of the four permittivity-extraction methods.",
        "Method Standards consumed Reference ε∗used Algorithm class Scalar C0 open none direct admittance.",
    ]

    for sample in samples:
        assert list(find_child_school_data(sample)) == []
        assert list(find_hr_personnel_data(sample)) == []
        assert list(find_legal_case_data(sample)) == []


def test_location_and_device_ids_require_labels() -> None:
    text = "GPS: 59.9139, 10.7522. MAC address: AA:BB:CC:DD:EE:FF. IMEI: 490154203237518."

    findings = list(find_location_device_ids(text))

    assert [(f.category, f.text) for f in findings] == [
        ("lokasjonsdata", "59.9139, 10.7522"),
        ("mac-adresse", "AA:BB:CC:DD:EE:FF"),
        ("imei", "490154203237518"),
    ]
    assert list(find_location_device_ids("Coordinates in math: 59.9139, 10.7522 without label")) == []


def test_bank_routing_details_are_detected_after_labels() -> None:
    text = "Routing number: 021000021. Sort code: 12-34-56. Account No: 12345678."

    findings = list(find_bank_routing_details(text))

    assert [(f.category, f.text) for f in findings] == [
        ("kontonummer", "021000021"),
        ("kontonummer", "12-34-56"),
        ("kontonummer", "12345678"),
    ]


def test_medical_fields_are_detected_without_ai() -> None:
    text = "Diagnosis: ADHD. Medication: Metformin 500 mg. MRN: ABC12345."

    findings = list(find_medical_fields(text))

    assert [(f.category, f.text) for f in findings] == [
        ("medisinsk opplysning", "ADHD"),
        ("medisinsk opplysning", "Metformin 500 mg"),
        ("medisinsk opplysning", "ABC12345"),
    ]


def test_confidential_label_lines_do_not_match_running_text() -> None:
    findings = list(find_confidential_label_lines("Confidential\nclassified by readiness\nRestricted:"))

    assert [(f.category, f.text) for f in findings] == [
        ("konfidensielt dokument (overskrift)", "Confidential"),
        ("konfidensielt dokument (overskrift)", "Restricted"),
    ]


def test_document_metadata_fields_are_detected() -> None:
    text = "Author: Kari Nordmann\nCompany: ACME AS\nBody: Author mentions are not labels here."

    findings = list(find_document_metadata_fields(text))

    assert [(f.category, f.text) for f in findings] == [
        ("dokumentmetadata", "Kari Nordmann"),
        ("dokumentmetadata", "ACME AS"),
    ]


def test_new_regex_categories_survive_default_scan_filter() -> None:
    text = (
        "SSN: 123-45-6789\n"
        "Annual salary: NOK 850 000\n"
        "Court case: HR-2026-001\n"
        "Student: Kari Nordmann\n"
        "GPS: 59.9139, 10.7522\n"
        "MAC address: AA:BB:CC:DD:EE:FF\n"
        "IMEI: 490154203237518\n"
        "Routing number: 021000021\n"
        "Diagnosis: ADHD\n"
        "Author: Kari Nordmann\n"
    )

    result = scan_text(text, language="en")
    categories = {f.category for f in result.findings}

    assert "tax identification number" in categories
    assert "lønn" in categories
    assert "juridisk forhold" in categories
    assert "barn/elevopplysning" in categories
    assert "lokasjonsdata" in categories
    assert "mac-adresse" in categories
    assert "imei" in categories
    assert "kontonummer" in categories
    assert "medisinsk opplysning" in categories
    assert "dokumentmetadata" in categories
