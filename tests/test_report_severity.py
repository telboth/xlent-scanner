"""Tester for risk-klassifisering og HTML-rapport (inkl. AI-dybdeskann-funn)."""
from xlent_scanner.risk import _category_severity
from xlent_scanner.report import generate_html, ai_severity
from xlent_scanner.models import ScanResult, Finding


# ── Alvorlighetsgrad-klassifisering ───────────────────────────────────────────

class TestSeverity:
    def test_cpr_is_svart(self):
        # Regresjon: dansk CPR var feilaktig klassifisert som gul
        assert _category_severity("cpr-nummer") == "svart"

    def test_national_ids_svart(self):
        for cat in ["fødselsnummer", "d-nummer", "personnummer (SV)",
                    "kontonummer", "kredittkort (Visa)",
                    "UK National Insurance Number", "US Social Security Number"]:
            assert _category_severity(cat) == "svart", cat

    def test_iban_and_secrets_rod(self):
        for cat in ["IBAN", "OpenAI API Key", "Passord i konfig"]:
            assert _category_severity(cat) == "rød", cat

    def test_pii_gul(self):
        for cat in ["e-post", "telefonnummer", "navn (person)",
                    "organisasjonsnummer", "nettadresse", "mulig personnummer (format)"]:
            assert _category_severity(cat) == "gul", cat


# ── AI-funn severity (stripper 🤖-prefiks) ────────────────────────────────────

class TestAiSeverity:
    def test_ai_prefix_stripped(self):
        assert ai_severity("🤖 Fødselsnummer") == "svart"
        assert ai_severity("🤖 IBAN") == "rød"
        assert ai_severity("🤖 Selskapsnavn") == "gul"
        assert ai_severity("🤖 Personnavn") == "gul"


# ── HTML-rapport ──────────────────────────────────────────────────────────────

def _result_with_findings():
    r = ScanResult(
        file_name="test.txt", file_size=100, text_length=50,
        text_preview="prøvetekst", original_text="prøvetekst",
        risk_level="rød", risk_summary="Sensitive funn", language="nb",
    )
    r.findings = [Finding(category="e-post", text="a@b.no", severity="gul")]
    return r


class TestReport:
    def test_html_renders(self):
        html = generate_html(_result_with_findings())
        assert "test.txt" in html
        assert "a@b.no" in html

    def test_ai_findings_merged_into_main_table(self):
        """AI-funn flettes inn i hovedlisten, ikke en separat seksjon."""
        html = generate_html(
            _result_with_findings(),
            ai_findings=[
                {"category": "🤖 Selskapsnavn", "text": "Shearwater", "context": "hos Shearwater"},
                {"category": "🤖 Fødselsnummer", "text": "01019000083", "context": "fnr"},
            ],
        )
        # Ingen separat AI-seksjon lenger
        assert "AI-dybdeskann-funn" not in html
        # AI-funn er i samme tabell
        assert "Shearwater" in html
        assert "01019000083" in html
        # Fnr fra AI skal få svart badge
        assert "badge-svart" in html
        # AI-badge (🔬) vises i kategoriraden
        assert "ai-badge" in html

    def test_ai_finding_whitelist_filtered(self):
        """AI-funn som finnes i whitelisten skal vises som grønn (hvitelistet)."""
        from unittest.mock import patch
        wl = {"shearwater"}
        with patch("xlent_scanner.whitelist.load_whitelist", return_value=wl):
            html = generate_html(
                _result_with_findings(),
                ai_findings=[{"category": "🤖 Selskapsnavn", "text": "Shearwater", "context": "x"}],
            )
        assert "Shearwater" in html
        assert "badge-grønn" in html      # vist som grønn/hvitelistet
        assert "Hvitelistet" in html

    def test_ai_duplicate_not_shown_twice(self):
        """AI-funn med samme tekst som regelbasert funn vises ikke dobbelt."""
        result = _result_with_findings()  # har a@b.no som e-post-funn
        html = generate_html(
            result,
            ai_findings=[{"category": "🤖 E-post", "text": "a@b.no", "context": "x"}],
        )
        # Kun én forekomst av a@b.no i funn-tabellen
        assert html.count("a@b.no") == html.count("<strong>a@b.no</strong>")

    def test_no_ai_badge_in_rows_without_ai_findings(self):
        """Ingen 🔬-badge i selve funnradene når det ikke er AI-funn."""
        html = generate_html(_result_with_findings(), ai_findings=[])
        # CSS-klassen .ai-badge eksisterer alltid, men brukes kun i funnrader
        assert '<span class="ai-badge">' not in html

    def test_ai_findings_none_safe(self):
        """ai_findings=None skal ikke krasje."""
        html = generate_html(_result_with_findings(), ai_findings=None)
        assert "test.txt" in html

    def test_whitelist_button_present_for_ai_findings(self):
        """AI-funn som IKKE er hvitelistet skal ha + Hviteliste-knapp."""
        html = generate_html(
            _result_with_findings(),
            ai_findings=[{"category": "🤖 Selskapsnavn", "text": "Shearwater", "context": "x"}],
        )
        assert "wl-btn" in html
