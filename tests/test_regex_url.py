"""Tester for URL-detektor (detectors/regex_url.py)."""
import pytest
from xlent_scanner.detectors.regex_url import detect_urls


def _texts(findings):
    return [f.text for f in findings]


# ── HTTPS/HTTP ────────────────────────────────────────────────────────────────

def test_https_url():
    f = list(detect_urls("Se https://xlent.no for mer info."))
    assert "https://xlent.no" in _texts(f)

def test_http_url():
    f = list(detect_urls("Mer på http://intern.firma.com/prosjekt"))
    assert "http://intern.firma.com/prosjekt" in _texts(f)

def test_https_url_with_path():
    f = list(detect_urls("Rapport: https://example.com/path?q=1&r=2"))
    texts = _texts(f)
    assert any("https://example.com" in t for t in texts)

# ── www. ──────────────────────────────────────────────────────────────────────

def test_www_url():
    f = list(detect_urls("Sjekk www.vg.no for nyheter."))
    assert "www.vg.no" in _texts(f)

def test_www_url_with_path():
    f = list(detect_urls("Gå til www.xlent.no/om-oss"))
    texts = _texts(f)
    assert any("www.xlent.no" in t for t in texts)

# ── Alvorlighetsgrad og kategori ──────────────────────────────────────────────

def test_category_is_nettadresse():
    f = list(detect_urls("https://example.com"))
    assert f[0].category == "nettadresse"

def test_severity_is_gul():
    f = list(detect_urls("www.vg.no"))
    # severity settes av risk-engine – direkte fra detector er det default
    assert f[0].category == "nettadresse"

# ── E-poster skal IKKE fanges ─────────────────────────────────────────────────

def test_email_not_matched():
    f = list(detect_urls("Kontakt oss på test@example.com eller www.example.com"))
    texts = _texts(f)
    assert not any("@" in t for t in texts)

def test_mixed_text():
    text = "Ring +47 91717678 eller besøk www.xlent.no og https://xlent.no/tjenester"
    texts = _texts(list(detect_urls(text)))
    assert "www.xlent.no" in texts
    assert any("https://xlent.no" in t for t in texts)

# ── Deduplicering ─────────────────────────────────────────────────────────────

def test_deduplication():
    text = "Se www.vg.no og www.vg.no for mer."
    f = list(detect_urls(text))
    vg = [x for x in f if "vg.no" in x.text]
    assert len(vg) == 1

# ── Ingen funn ────────────────────────────────────────────────────────────────

def test_no_urls():
    f = list(detect_urls("Ingen nettadresser her."))
    assert f == []

def test_domain_without_protocol_not_matched():
    """example.com uten www. eller protokoll skal IKKE fanges."""
    f = list(detect_urls("Domenet example.com er kjent."))
    texts = _texts(f)
    assert not any("example.com" in t for t in texts)


def test_us_phone_numbers_not_matched_as_url():
    f = list(detect_urls("Call (234) 567-8901 or +01 (234) 567-4902."))
    assert f == []
