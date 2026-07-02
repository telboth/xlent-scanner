"""Integrasjonstest: skann i_english.docx og valider funn.

Testfilen inneholder (fra manuell gjennomgang):
  - E-post:         Thomas.elboth@xlent.no, t.elboth@gmail.com
  - Telefon:        91717680, +47 91717678, +4791717678, 0047 12345678
  - Personnavn:     Thomas Elboth, Erna Solberg, Frank Jensen, Nils Hansen,
                    Silje Nord, Susanne Rentch-Smith, Åse Bratberg
  - Kontonummer:    1730.1777.922 (GYLDIG), 17301777922 (GYLDIG)
                    1234 5678 910 (UGYLDIG – skal ikke finnes)
  - Fødselsnummer:  210572 12345 og 21057212345 (begge UGYLDIG – skal ikke finnes)
  - Nettadresser:   www.vg.no, www.db.no (kun tekst, ikke regex-detektor i rask skann)
"""
from __future__ import annotations

import pathlib
import pytest

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "i_english.docx"


@pytest.fixture(scope="module")
def scan_result():
    """Skann testfilen én gang for alle tester i dette modul."""
    from xlent_scanner.scanner import scan_file
    result = scan_file(str(FIXTURE))
    assert result.error is None, f"Skanning feilet: {result.error}"
    return result


def _category_texts(result, category: str) -> list[str]:
    """Hent alle fund-tekster for en gitt kategori."""
    return [f.text for f in result.findings if f.category == category]


def _all_texts(result) -> list[str]:
    return [f.text for f in result.findings]


def _all_categories(result) -> set[str]:
    return {f.category for f in result.findings}


# ── Grunnleggende resultatkontroll ────────────────────────────────────────────

class TestBasicResult:
    def test_no_error(self, scan_result):
        assert scan_result.error is None

    def test_has_findings(self, scan_result):
        assert len(scan_result.findings) > 0

    def test_risk_level_not_green(self, scan_result):
        # Filen inneholder persondata → bør ikke være grønn
        assert scan_result.risk_level != "grønn"


# ── E-post ────────────────────────────────────────────────────────────────────

class TestEmails:
    def test_xlent_email_found(self, scan_result):
        texts = _category_texts(scan_result, "e-post")
        # Case-insensitiv sammenligning
        lower = [t.lower() for t in texts]
        assert "thomas.elboth@xlent.no" in lower, f"Fant e-poster: {texts}"

    def test_gmail_found(self, scan_result):
        texts = _category_texts(scan_result, "e-post")
        lower = [t.lower() for t in texts]
        assert "t.elboth@gmail.com" in lower, f"Fant e-poster: {texts}"


# ── Telefon ───────────────────────────────────────────────────────────────────

class TestPhones:
    def _phone_texts(self, scan_result) -> list[str]:
        return _category_texts(scan_result, "telefonnummer")

    def test_8digit_found(self, scan_result):
        phones = self._phone_texts(scan_result)
        # 91717680 skal finnes
        assert any("91717680" in p for p in phones), f"Fant telefoner: {phones}"

    def test_plus47_found(self, scan_result):
        phones = self._phone_texts(scan_result)
        assert any("+47" in p for p in phones), f"Fant telefoner: {phones}"

    def test_0047_found(self, scan_result):
        phones = self._phone_texts(scan_result)
        assert any("0047" in p for p in phones), f"Fant telefoner: {phones}"


# ── Kontonummer ───────────────────────────────────────────────────────────────

class TestAccountNumbers:
    def _acct_texts(self, scan_result) -> list[str]:
        return _category_texts(scan_result, "kontonummer")

    def test_valid_konto_dot_format(self, scan_result):
        texts = self._acct_texts(scan_result)
        assert any("1730" in t for t in texts), \
            f"Forventer 1730.1777.922 – fant: {texts}"

    def test_invalid_konto_not_found(self, scan_result):
        texts = self._acct_texts(scan_result)
        # 1234 5678 910 har ugyldig mod-11 → skal IKKE finnes
        joined = " ".join(texts)
        assert "1234" not in joined or all(
            "1234" not in t or "5678" not in t for t in texts
        ), f"Ugyldig konto 1234 5678 910 skal ikke finnes: {texts}"


# ── Fødselsnummer ─────────────────────────────────────────────────────────────

class TestFnr:
    def test_invalid_fnr_not_found(self, scan_result):
        # 21057212345 og 210572 12345 er UGYLDIGE → skal ikke gi funn
        fnr_texts = _category_texts(scan_result, "fødselsnummer")
        dnr_texts = _category_texts(scan_result, "d-nummer")
        all_ids = " ".join(fnr_texts + dnr_texts)
        assert "210572" not in all_ids, \
            f"Ugyldig FNR 210572* skal ikke finnes: {fnr_texts}"


# ── Ingen falske positiver på nettadresser i rask skann ─────────────────────

class TestNoWebAddressFalsePositive:
    def test_www_not_in_email(self, scan_result):
        # www.vg.no og www.db.no er nettadresser, ikke e-poster
        email_texts = _category_texts(scan_result, "e-post")
        assert not any("www." in e for e in email_texts), \
            f"www.* skal ikke matchet som e-post: {email_texts}"


def test_merged_id_category_includes_birth_date():
    from xlent_scanner.scanner import scan_text

    result = scan_text("Fødselsdato: 01.02.1980", language="nb", categories=["id"])

    assert ("fødselsdato", "01.02.1980") in [(f.category, f.text) for f in result.findings]


def test_merged_bank_category_includes_credit_cards():
    from xlent_scanner.scanner import scan_text

    result = scan_text("Kort: 4532015112830002", language="nb", categories=["konto"])

    assert any(f.category.startswith("kredittkort") for f in result.findings)
