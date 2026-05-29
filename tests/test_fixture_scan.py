"""Integrasjonstester som scanner tests/fixtures/sensitiv_nb.txt og .pdf.

Verifikasjon:
  - Alle forventede sensitive kategorier detekteres
  - Ingen funn i en ren tekst
  - Risikonivå er korrekt (svart for personnummer)
  - PDF og TXT gir overlappende funn
"""
import pytest
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
TXT_FILE = FIXTURES / "sensitiv_nb.txt"
PDF_FILE = FIXTURES / "sensitiv_nb.pdf"


# ── Hjelpere ───────────────────────────────────────────────────────────────────

def _cats(result):
    return {f.category for f in result.findings}


def _has_category(result, prefix: str) -> bool:
    return any(f.category.lower().startswith(prefix.lower()) for f in result.findings)


# ── TXT-fixture-scan ───────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def txt_result():
    from xlent_scanner.scanner import scan_file
    return scan_file(TXT_FILE, language="nb")


class TestTxtFixtureScan:
    def test_file_readable(self, txt_result):
        assert txt_result.error is None, f"Scan-feil: {txt_result.error}"
        assert txt_result.text_length > 500

    def test_risk_level_svart(self, txt_result):
        """Fødselsnummer er svart → samlet nivå skal være svart."""
        assert txt_result.risk_level == "svart"

    def test_finds_fnr(self, txt_result):
        assert _has_category(txt_result, "fødselsnummer"), "Fødselsnummer ikke funnet"

    def test_finds_dnr(self, txt_result):
        assert _has_category(txt_result, "d-nummer"), "D-nummer ikke funnet"

    def test_finds_kontonummer(self, txt_result):
        assert _has_category(txt_result, "kontonummer"), "Kontonummer ikke funnet"

    def test_fnr_not_also_kontonummer(self, txt_result):
        """Regresjon: fnr 01019000083 skal ikke dobbelt-flagges."""
        fnr_texts = {f.text for f in txt_result.findings if f.category == "fødselsnummer"}
        konto_texts = {f.text for f in txt_result.findings if f.category == "kontonummer"}
        overlap = fnr_texts & konto_texts
        assert not overlap, f"Disse er flagget som BÅDE fnr og konto: {overlap}"

    def test_finds_orgnr(self, txt_result):
        assert _has_category(txt_result, "organisasjonsnummer"), "Org.nr ikke funnet"

    def test_finds_email(self, txt_result):
        assert _has_category(txt_result, "e-post"), "E-post ikke funnet"

    def test_finds_telefon(self, txt_result):
        assert _has_category(txt_result, "telefonnummer"), "Telefonnummer ikke funnet"

    def test_finds_iban(self, txt_result):
        assert _has_category(txt_result, "iban"), "IBAN ikke funnet"

    def test_finds_creditcard(self, txt_result):
        assert _has_category(txt_result, "kredittkort"), "Kredittkort ikke funnet"

    def test_finds_confidential_marker(self, txt_result):
        assert _has_category(txt_result, "konfidensielt"), "Konfidensielt-markør ikke funnet"

    def test_finds_url(self, txt_result):
        assert _has_category(txt_result, "nettadresse"), "URL ikke funnet"

    def test_finds_financial(self, txt_result):
        found = any(
            _has_category(txt_result, cat)
            for cat in ("timepris", "dagspris", "prosjektsum", "margin", "rabatt")
        )
        assert found, "Ingen finansielle funn detektert"

    def test_finds_api_key_or_secret(self, txt_result):
        found = any(
            _has_category(txt_result, cat)
            for cat in ("openai", "aws", "github", "jwt", "passord", "høy-entropi", "konfigurasjons")
        )
        assert found, "Ingen secrets/API-nøkler funnet"

    def test_language_detected_nb(self, txt_result):
        assert txt_result.language == "nb"


# ── PDF-fixture-scan ───────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def pdf_result():
    from xlent_scanner.scanner import scan_file
    return scan_file(PDF_FILE, language="nb")


class TestPdfFixtureScan:
    def test_pdf_readable(self, pdf_result):
        assert pdf_result.error is None, f"PDF-scan-feil: {pdf_result.error}"
        assert pdf_result.text_length > 200

    def test_pdf_risk_level_svart(self, pdf_result):
        assert pdf_result.risk_level == "svart"

    def test_pdf_finds_fnr(self, pdf_result):
        assert _has_category(pdf_result, "fødselsnummer")

    def test_pdf_no_fnr_as_konto(self, pdf_result):
        fnr_texts = {f.text for f in pdf_result.findings if f.category == "fødselsnummer"}
        konto_texts = {f.text for f in pdf_result.findings if f.category == "kontonummer"}
        assert not (fnr_texts & konto_texts)

    def test_pdf_finds_iban(self, pdf_result):
        assert _has_category(pdf_result, "iban")

    def test_pdf_finds_url(self, pdf_result):
        assert _has_category(pdf_result, "nettadresse")


# ── Ren tekst – ingen falske positiver ────────────────────────────────────────

class TestCleanText:
    def test_no_findings_in_clean_text(self):
        from xlent_scanner.scanner import scan_text
        txt = (
            "Dette er en helt vanlig tekst uten sensitiv informasjon. "
            "Vi diskuterer prosjektet og fremdriften generelt. "
            "Møtet er satt til tirsdag klokken 14:00 i møterom 3."
        )
        result = scan_text(txt, language="nb")
        # Tillat kun lave alvorlighetsgrader
        high_severity = [f for f in result.findings if f.severity in ("rød", "svart")]
        assert high_severity == [], f"Falske positiver (rød/svart): {[(f.category, f.text) for f in high_severity]}"

    def test_risk_level_green_for_clean_text(self):
        from xlent_scanner.scanner import scan_text
        txt = "Generell informasjon uten persondata."
        result = scan_text(txt, language="nb")
        assert result.risk_level in ("grønn", "gul")  # ingen svart/rød


# ── Nye filformater ────────────────────────────────────────────────────────────

class TestNewFileFormats:
    def test_csv_scan(self, tmp_path):
        from xlent_scanner.scanner import scan_file
        csv = tmp_path / "data.csv"
        csv.write_text(
            "navn,epost,fnr\n"
            "Per Hansen,per@test.no,01019000083\n",
            encoding="utf-8",
        )
        result = scan_file(csv)
        assert result.error is None
        assert _has_category(result, "e-post") or _has_category(result, "fødselsnummer")

    def test_eml_scan(self, tmp_path):
        from xlent_scanner.scanner import scan_file
        eml = tmp_path / "mail.eml"
        eml.write_text(
            "From: avsender@xlent.no\n"
            "To: mottaker@firma.no\n"
            "Subject: Konfidensiell rapport\n"
            "\n"
            "Hei Per Hansen, fnr 01019000083.\n",
            encoding="utf-8",
        )
        result = scan_file(eml)
        assert result.error is None
        assert result.text_length > 0
        assert _has_category(result, "e-post")

    def test_txt_scan_supported(self, tmp_path):
        from xlent_scanner.scanner import scan_file
        f = tmp_path / "notat.txt"
        f.write_text("thomas@xlent.no bruker kontonr 1000.00.00006", encoding="utf-8")
        result = scan_file(f)
        assert result.error is None
        assert _has_category(result, "e-post") or _has_category(result, "kontonummer")

    def test_odt_scan(self, tmp_path):
        """ODT: zip med content.xml."""
        import zipfile, io
        from xlent_scanner.scanner import scan_file

        content_xml = """<?xml version="1.0" encoding="UTF-8"?>
<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
                         xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">
  <office:body><office:text>
    <text:p>Epost: test@example.com</text:p>
    <text:p>Fnr: 01019000083</text:p>
  </office:text></office:body>
</office:document-content>"""

        odt_path = tmp_path / "dokument.odt"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("mimetype", "application/vnd.oasis.opendocument.text")
            zf.writestr("content.xml", content_xml)
        odt_path.write_bytes(buf.getvalue())

        result = scan_file(odt_path)
        assert result.error is None
        assert result.text_length > 0
