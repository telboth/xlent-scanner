from xlent_scanner.language import detect_language, resolve_language


def test_unclear_short_text_uses_english_fallback():
    assert detect_language("123 abc") == "en"


def test_unknown_requested_language_uses_english_fallback():
    assert resolve_language("unknown", "Dette er en tekst.") == "en"


def test_explicit_supported_language_is_preserved():
    assert resolve_language("nb", "Kort tekst") == "nb"
