from xlent_scanner.detectors.regex_extra import find_swift


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
