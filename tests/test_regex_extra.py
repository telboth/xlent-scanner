from xlent_scanner.detectors.regex_extra import (
    detect_extra,
    find_tax_id,
    find_labeled_phone_or_fax,
    find_po_box_address,
    find_street_address,
    find_swift,
)


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
        "Tax Id 987654321",
        "tax identification number: AB-123456789",
        "TIN: 12 345 678",
    ]

    findings = [finding for sample in samples for finding in find_tax_id(sample)]

    assert [(f.category, f.text) for f in findings] == [
        ("tax identification number", "123-45-6789"),
        ("tax identification number", "987654321"),
        ("tax identification number", "AB-123456789"),
        ("tax identification number", "12 345 678"),
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
