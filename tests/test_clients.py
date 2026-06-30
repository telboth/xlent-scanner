from xlent_scanner.detectors.clients import find_company_suffix_names
from xlent_scanner.scanner import scan_text


def test_company_suffix_names_are_detected_before_legal_suffixes():
    text = "Invoice to Example Consulting AS, Global Shipping LTD and Northwind LLC."

    findings = list(find_company_suffix_names(text))

    assert [(f.category, f.text) for f in findings] == [
        ("kundenavn", "Example Consulting AS"),
        ("kundenavn", "Global Shipping LTD"),
        ("kundenavn", "Northwind LLC"),
    ]


def test_company_suffix_detection_is_controlled_by_firmanavn_category():
    text = "Invoice to Example Consulting AS. Contact test@example.com."

    with_company = scan_text(text, language="en", categories=["klient"])
    without_company = scan_text(text, language="en", categories=["epost"])

    assert any(f.category == "kundenavn" and f.text == "Example Consulting AS" for f in with_company.findings)
    assert all(f.category != "kundenavn" for f in without_company.findings)


def test_tax_id_detection_is_controlled_by_person_id_category():
    text = "Employee Tax ID: 123-45-6789. Contact test@example.com."

    with_id = scan_text(text, language="en", categories=["id"])
    without_id = scan_text(text, language="en", categories=["epost"])

    assert any(
        f.category == "tax identification number" and f.text == "123-45-6789"
        for f in with_id.findings
    )
    assert all(f.category != "tax identification number" for f in without_id.findings)


def test_street_address_detection_is_controlled_by_address_category():
    text = "Ship to Baker Street 221B. Contact test@example.com."

    with_address = scan_text(text, language="en", categories=["adresse"])
    without_address = scan_text(text, language="en", categories=["epost"])

    assert any(
        f.category == "fysisk adresse" and f.text == "Baker Street 221B"
        for f in with_address.findings
    )
    assert all(f.category != "fysisk adresse" for f in without_address.findings)
