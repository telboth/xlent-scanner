"""Tester for anonymize.py og patch.py.

Dekker:
  - Konsistent alfa-merking (Person A, Person B, ...)
  - Konsistent num-merking (Konto 1, Epost 1, ...)
  - Lengste-treff prioritert (to-fase token-strategi)
  - Ingen placeholder-kollisjon
  - build_replacements: raw_text brukes foran text
  - anonymize_text: full erstatning
"""
import pytest
from xlent_scanner.anonymize import anonymize_text, build_replacements
from xlent_scanner.models import Finding


# ── Hjelpere ──────────────────────────────────────────────────────────────────

def _f(category: str, text: str, raw_text: str = "") -> Finding:
    return Finding(category=category, text=text, raw_text=raw_text)


# ── build_replacements ────────────────────────────────────────────────────────

class TestBuildReplacements:
    def test_name_gets_alpha_label(self):
        r = build_replacements([_f("navn (person)", "Per Hansen")])
        assert r.get("Per Hansen") == "<Person A>"

    def test_two_names_get_ab(self):
        r = build_replacements([
            _f("navn (person)", "Per Hansen"),
            _f("navn (person)", "Kari Olsen"),
        ])
        assert r["Per Hansen"] == "<Person A>"
        assert r["Kari Olsen"] == "<Person B>"

    def test_account_gets_numeric_label(self):
        r = build_replacements([_f("kontonummer", "1000.00.00006")])
        assert r.get("1000.00.00006") == "<Konto 1>"

    def test_email_gets_numeric_label(self):
        r = build_replacements([_f("e-post", "test@example.com")])
        assert r.get("test@example.com") == "<Epost 1>"

    def test_raw_text_preferred_over_text(self):
        """raw_text (umasket) skal brukes som erstatningsnøkkel."""
        r = build_replacements([_f("fødselsnummer", "010190***", raw_text="01019000083")])
        assert "01019000083" in r

    def test_masked_text_skipped(self):
        """Tekst med «…» (maskeringsmarkør) skal hoppes over."""
        r = build_replacements([_f("IBAN", "NO80…0006")])
        assert r == {}

    def test_warning_finding_skipped(self):
        r = build_replacements([_f("⚠ NER ikke tilgjengelig", "spaCy feil")])
        assert r == {}

    def test_same_name_same_label(self):
        """Duplikat-verdi skal gi identisk etikett."""
        r = build_replacements([
            _f("navn (person)", "Per Hansen"),
            _f("navn (person)", "Per Hansen"),
        ])
        vals = list(r.values())
        assert vals.count("<Person A>") == 1  # bare én oppføring

    def test_company_gets_alpha_label(self):
        r = build_replacements([_f("kundenavn", "Nordea Bank")])
        assert r.get("Nordea Bank") == "<Selskap A>"


# ── anonymize_text ────────────────────────────────────────────────────────────

class TestAnonymizeText:
    def test_basic_replacement(self):
        findings = [_f("e-post", "test@example.com", "test@example.com")]
        txt = "Send til test@example.com takk"
        out = anonymize_text(txt, findings)
        assert "test@example.com" not in out
        assert "<Epost" in out

    def test_longest_first_prevents_leakage(self):
        """«Per» skal ikke konsumere starten av «Per Hansen»."""
        findings = [
            _f("navn (person)", "Per", "Per"),
            _f("navn (person)", "Per Hansen", "Per Hansen"),
        ]
        txt = "Kontakt Per Hansen eller bare Per."
        out = anonymize_text(txt, findings)
        assert "Hansen" not in out, f"Etternavn lekker: {out}"

    def test_no_placeholder_collision(self):
        """Plassholder-tekst (f.eks. <Person B>) skal ikke treffes av neste runde."""
        findings = [
            _f("navn (person)", "Per", "Per"),
            _f("navn (person)", "Per Hansen", "Per Hansen"),
        ]
        txt = "Per Hansen og Per."
        out = anonymize_text(txt, findings)
        # Ingen doble <>-nøsting
        assert "<<" not in out, f"Dobbel-nøsting: {out}"
        assert ">>" not in out

    def test_empty_findings(self):
        txt = "Ingen funn her."
        out = anonymize_text(txt, [])
        assert out == txt

    def test_multiple_occurrences_all_replaced(self):
        findings = [_f("e-post", "a@b.no", "a@b.no")]
        txt = "a@b.no er brukt to ganger: a@b.no"
        out = anonymize_text(txt, findings)
        assert out.count("a@b.no") == 0
        assert out.count("<Epost 1>") == 2

    def test_ai_finding_replaced_with_anonymisert(self):
        findings = [_f("🤖 Personnavn", "Ola Normann", "Ola Normann")]
        txt = "Ola Normann er kontakt."
        out = anonymize_text(txt, findings)
        assert "Ola Normann" not in out
        assert "[ANONYMISERT]" in out

    def test_ai_finding_control_chars_are_removed_from_replacement_key(self):
        replacements = build_replacements([_f("🤖 Personnavn", "Ola\x00Normann\x07")])
        assert replacements == {"OlaNormann": "[ANONYMISERT]"}

    def test_fixed_placeholder_for_credit_card(self):
        findings = [_f("kredittkort (Visa)", "4532 **** **** 0002", raw_text="4532015112830002")]
        txt = "Betalt med 4532015112830002"
        out = anonymize_text(txt, findings)
        assert "4532015112830002" not in out

    def test_two_accounts_different_labels(self):
        findings = [
            _f("kontonummer", "1000.00.00006", "10000000006"),
            _f("kontonummer", "2000.00.00001", "20000000001"),
        ]
        txt = "Konto1: 10000000006 og Konto2: 20000000001"
        out = anonymize_text(txt, findings)
        assert "<Konto 1>" in out
        assert "<Konto 2>" in out


# ── Regresjon: to-fase tokenisering ──────────────────────────────────────────

class TestTwoPhaseTokenization:
    def test_null_byte_never_in_input(self):
        """Null-bytes finnes aldri i normale dokumenter."""
        txt = "Per Hansen bor i Oslo."
        findings = [_f("navn (person)", "Per", "Per"),
                    _f("navn (person)", "Per Hansen", "Per Hansen")]
        out = anonymize_text(txt, findings)
        assert "\x00" not in out, "Midlertidig token lekker til output"

    def test_three_overlapping(self):
        """«Erik», «Per Erik», «Per Erik Hansen» — bare lengste skal treffe."""
        findings = [
            _f("navn (person)", "Erik",           "Erik"),
            _f("navn (person)", "Per Erik",       "Per Erik"),
            _f("navn (person)", "Per Erik Hansen", "Per Erik Hansen"),
        ]
        txt = "Hei Per Erik Hansen!"
        out = anonymize_text(txt, findings)
        assert "Per Erik Hansen" not in out
        assert "Hansen" not in out, f"Hansen lekker: {out}"
        assert "<<" not in out

    def test_short_numeric_findings_do_not_corrupt_deep_scan_budget(self):
        findings = [
            _f("🤖 Finansielt tall", "30", "30"),
            _f("🤖 Finansielt tall", "20", "20"),
            _f("🤖 Finansielt tall", "10", "10"),
            _f("🤖 Finansielt tall", "100", "100"),
            _f("mulig personnummer", "0", "0"),
            _f("navn (person)", "1", "1"),
            _f("telefonnummer", "2", "2"),
        ]
        txt = (
            "Item | Cost (NOK) | Amount | Total Cost (NOK)\n"
            "Bread | 30 | 2 | 60\n"
            "Milk | 20 | 1 | 20\n"
            "Eggs | 10 | 10 | 100"
        )
        out = anonymize_text(txt, findings)

        assert "\x00" not in out
        assert "29<" not in out
        assert "30<" not in out
        assert "20<" not in out
        assert "10<" not in out
        assert "100<" not in out
        assert "60" in out


# ── Integrasjon: scanner + anonymize ─────────────────────────────────────────

class TestScannerAnonymizeIntegration:
    def test_fnr_anonymized_consistently(self):
        """Scan → anonymiser fnr → fnr skal ikke finnes i output."""
        from xlent_scanner.scanner import scan_text
        txt = "Personnummer: 01019000083 er registrert."
        result = scan_text(txt)
        fnr_findings = [f for f in result.findings if f.category == "fødselsnummer"]
        assert len(fnr_findings) >= 1
        out = anonymize_text(txt, fnr_findings)
        assert "01019000083" not in out
        assert "<FNR" in out
