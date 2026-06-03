"""Enhetstester for alle detektormoduler.

Dekker:
  - regex_no: fødselsnummer, d-nummer, kontonummer, org.nr, telefon, e-post
  - regex_sv: personnummer, samordningsnummer, org.nr, telefon, bankgiro, plusgiro
  - regex_en: UK NI-nummer, US SSN
  - creditcards: Visa, Mastercard, Amex (Luhn + prefix)
  - iban: NO og GB IBAN (MOD-97)
  - secrets: OpenAI-nøkkel, AWS Access Key, GitHub-token, JWT
  - financials: timepris, dagspris, prosjektsum, margin, rabatt
  - keywords: konfidensielle markører, konfigurasjonsord
  - regex_url: HTTP/HTTPS og www.
"""
import pytest

# ────────────────────────────────────────────────────────────
#  Hjelpere
# ────────────────────────────────────────────────────────────

def _cats(findings):
    return [f.category for f in findings]

def _texts(findings):
    return [f.text for f in findings]


# ════════════════════════════════════════════════════════════
#  regex_no
# ════════════════════════════════════════════════════════════

from xlent_scanner.detectors.regex_no import (
    find_fnr, find_kontonummer, find_orgnr, find_telefon, find_emails,
    detect_no_specific,
)

class TestFnr:
    def test_valid_fnr(self):
        f = list(find_fnr("Fnr: 01019000083"))
        assert len(f) == 1
        assert f[0].category == "fødselsnummer"
        assert "01019000083" in f[0].text

    def test_valid_dnr(self):
        f = list(find_fnr("D-nr: 41019000077"))
        assert len(f) == 1
        assert f[0].category == "d-nummer"

    def test_fnr_with_space(self):
        """6+space+5 format."""
        f = list(find_fnr("Ref: 010190 00083"))
        assert len(f) == 1
        assert f[0].category == "fødselsnummer"

    def test_invalid_checksum_caught_as_possible(self):
        """Feil kontrollsiffer men gyldig datoformat → 'mulig personnummer (format)'."""
        f = list(find_fnr("21057212345"))          # brukertestcase: feil mod-11
        assert len(f) == 1
        assert f[0].category == "mulig personnummer (format)"

    def test_invalid_checksum_with_space(self):
        """6+space+5-format med feil checksum skal også fanges."""
        f = list(find_fnr("My personnummer is 210572 12345 ok"))
        assert len(f) == 1
        assert f[0].category == "mulig personnummer (format)"

    def test_invalid_date_not_caught(self):
        """Dag=32 finnes ikke → ingen funn overhodet."""
        f = list(find_fnr("32139000000"))
        assert f == []

    def test_invalid_month_not_caught(self):
        """Mnd=13 finnes ikke → ingen funn."""
        f = list(find_fnr("01139000000"))
        assert f == []

    def test_valid_beats_possible(self):
        """Gyldig personnummer skal gi 'fødselsnummer', ikke 'mulig personnummer'."""
        f = list(find_fnr("01019000083"))
        assert len(f) == 1
        assert f[0].category == "fødselsnummer"


class TestKontonummer:
    def test_4_2_5_format(self):
        f = list(find_kontonummer("Konto: 1000.00.00006"))
        assert len(f) == 1
        assert f[0].category == "kontonummer"

    def test_raw_11_digits(self):
        f = list(find_kontonummer("10000000006"))
        assert len(f) == 1

    def test_fnr_not_flagged_as_konto(self):
        """01019000083 er gyldig fnr MEN skal IKKE flagges som kontonummer."""
        f = list(find_kontonummer("01019000083"))
        assert f == [], "fnr skal ikke dobbelt-flagges som kontonummer"

    def test_invalid_checksum(self):
        f = list(find_kontonummer("1000.00.00007"))  # feil kontrollsiffer
        assert f == []


class TestOrgnr:
    def test_valid_orgnr(self):
        f = list(find_orgnr("Org.nr: 800000009"))
        assert len(f) == 1
        assert f[0].category == "organisasjonsnummer"

    def test_with_spaces(self):
        f = list(find_orgnr("800 000 009"))
        assert len(f) == 1

    def test_invalid_checksum(self):
        f = list(find_orgnr("800000008"))
        assert f == []

    def test_must_start_with_8_or_9(self):
        f = list(find_orgnr("700000004"))
        assert f == []


class TestTelefon:
    def test_international_prefix(self):
        f = list(find_telefon("+47 41234567"))
        assert len(f) == 1

    def test_mobile_3_2_3(self):
        f = list(find_telefon("412 34 567"))
        assert len(f) == 1

    def test_mobile_compact(self):
        f = list(find_telefon("41234567"))
        assert len(f) == 1

    def test_landline(self):
        f = list(find_telefon("22 34 56 78"))
        assert len(f) == 1

    def test_no_false_positive_on_org_nr(self):
        """800000009 er ikke et norsk telefonnummer."""
        f = list(find_telefon("800000009"))
        assert f == []

    def test_no_false_positive_on_year_range(self):
        f = list(find_telefon("Budsjettperiode 2025-2026"))
        assert f == []

    def test_no_false_positive_on_iso_date(self):
        f = list(find_telefon("Signert 2021-03-09"))
        assert f == []


class TestEmail:
    def test_simple_email(self):
        f = list(find_emails("test@example.com"))
        assert len(f) == 1
        assert f[0].category == "e-post"

    def test_subdomain_email(self):
        f = list(find_emails("Send til user@mail.firma.no for svar."))
        assert len(f) == 1

    def test_multiple_emails(self):
        f = list(find_emails("a@b.no og c@d.no"))
        assert len(f) == 2

    def test_no_false_positive_bare_at(self):
        f = list(find_emails("@ er ikke en epost"))
        assert f == []


class TestNoDoublingBug:
    """Regresjontest: fnr skal ikke dobbelt-flagges."""
    def test_scan_fnr_gives_single_finding(self):
        findings = detect_no_specific("Kontaktperson: 01019000083")
        cats = _cats(findings)
        assert cats.count("fødselsnummer") == 1, "skal ha nøyaktig ett fnr-funn"
        assert "kontonummer" not in cats, "fnr skal IKKE flagges som kontonummer"


# ════════════════════════════════════════════════════════════
#  regex_sv
# ════════════════════════════════════════════════════════════

from xlent_scanner.detectors.regex_sv import (
    find_persnr, find_orgnr_sv, find_telefon_sv, find_bankgiro, find_plusgiro,
)


class TestSvPersonnummer:
    def test_valid_personnummer(self):
        f = list(find_persnr("811218-0008"))
        assert len(f) == 1
        assert f[0].category == "personnummer (SV)"

    def test_12_digit_format(self):
        f = list(find_persnr("19811218-0008"))
        assert len(f) == 1

    def test_samordningsnummer(self):
        # Dag + 60 = samordningsnummer
        # 811278-0008 → dag=78-60=18, gyldig om Luhn stemmer
        # Finn et gyldig samordningsnummer
        from xlent_scanner.detectors.regex_sv import _validate_persnr
        found = None
        for n in range(0, 10000):
            r = _validate_persnr("811278", "-", f"{n:04d}")
            if r == "samordningsnummer (SV)":
                found = f"811278-{n:04d}"
                break
        if found:
            f2 = list(find_persnr(found))
            assert len(f2) == 1
            assert f2[0].category == "samordningsnummer (SV)"

    def test_invalid_checksum(self):
        f = list(find_persnr("811218-0009"))  # endret siste siffer
        assert f == []


class TestSvOrgnr:
    def test_valid_orgnr_sv(self):
        f = list(find_orgnr_sv("Org: 556000-0001"))
        assert len(f) == 1
        assert f[0].category == "organisasjonsnummer (SV)"

    def test_invalid_digit2(self):
        """Siffra[2] < 2 → ikke org.nr."""
        f = list(find_orgnr_sv("810101-0001"))
        # Kan matche personnummer-format – men ikke org.nr
        for finding in f:
            assert finding.category != "organisasjonsnummer (SV)"


class TestSvBankgiro:
    def test_bankgiro_keyword(self):
        f = list(find_bankgiro("Bankgiro: 123-4567"))
        assert len(f) == 1
        assert f[0].category == "bankgiro (SV)"

    def test_plusgiro_keyword(self):
        f = list(find_plusgiro("Plusgiro: 12345-6"))
        assert len(f) == 1
        assert f[0].category == "plusgiro (SV)"

    def test_no_keyword_no_match(self):
        """Bankgiro uten nøkkelord skal ikke fanges."""
        f = list(find_bankgiro("123-4567"))
        assert f == []


# ════════════════════════════════════════════════════════════
#  regex_en
# ════════════════════════════════════════════════════════════

from xlent_scanner.detectors.regex_en import find_uk_ni, find_us_phone, find_us_ssn


class TestUkNi:
    def test_valid_ni(self):
        f = list(find_uk_ni("NI: AB 12 34 56 A"))
        assert len(f) == 1
        assert f[0].category == "UK National Insurance Number"

    def test_invalid_prefix_bg(self):
        f = list(find_uk_ni("BG 12 34 56 A"))
        assert f == []

    def test_invalid_suffix_e(self):
        f = list(find_uk_ni("AB 12 34 56 E"))
        assert f == []


class TestUsSsn:
    def test_valid_ssn(self):
        f = list(find_us_ssn("SSN: 123-45-6789"))
        assert len(f) == 1
        assert f[0].category == "US Social Security Number"

    def test_area_000_invalid(self):
        f = list(find_us_ssn("000-45-6789"))
        assert f == []

    def test_area_666_invalid(self):
        f = list(find_us_ssn("666-45-6789"))
        assert f == []

    def test_area_900_invalid(self):
        f = list(find_us_ssn("900-45-6789"))
        assert f == []

    def test_group_00_invalid(self):
        f = list(find_us_ssn("123-00-6789"))
        assert f == []

    def test_no_hyphens_no_match(self):
        """Uten bindestrek: for mange falske positiver — ignorer."""
        f = list(find_us_ssn("123456789"))
        assert f == []


class TestUsPhone:
    def test_parenthesized_us_phone(self):
        f = list(find_us_phone("Call (234) 567-8901"))
        assert len(f) == 1
        assert f[0].category == "telefonnummer"
        assert f[0].text == "(234) 567-8901"

    def test_plus01_us_phone(self):
        f = list(find_us_phone("Call +01 (234) 567-4902"))
        assert len(f) == 1
        assert f[0].text == "+01 (234) 567-4902"

    def test_reject_invalid_area_prefix(self):
        f = list(find_us_phone("Call (034) 567-8901"))
        assert f == []


# ════════════════════════════════════════════════════════════
#  creditcards
# ════════════════════════════════════════════════════════════

from xlent_scanner.detectors.creditcards import find_creditcards


class TestCreditCards:
    def test_visa(self):
        f = list(find_creditcards("Kort: 4532015112830002"))
        assert len(f) == 1
        assert "Visa" in f[0].category
        assert "****" in f[0].text  # maskert

    def test_mastercard(self):
        f = list(find_creditcards("5500 0000 0000 0004"))
        assert len(f) == 1
        assert "Mastercard" in f[0].category

    def test_amex(self):
        f = list(find_creditcards("3714 496353 98431"))
        assert len(f) == 1
        assert "American Express" in f[0].category

    def test_invalid_luhn(self):
        f = list(find_creditcards("4532015112830003"))  # feil Luhn
        assert f == []

    def test_unknown_prefix_not_matched(self):
        """Ukjent BIN-prefix → ingen funn."""
        f = list(find_creditcards("1234567890123456"))
        assert f == []

    def test_deduplication(self):
        f = list(find_creditcards("4532015112830002 og igjen 4532015112830002"))
        assert len(f) == 1


# ════════════════════════════════════════════════════════════
#  iban
# ════════════════════════════════════════════════════════════

from xlent_scanner.detectors.iban import find_iban


class TestIban:
    def test_no_iban(self):
        f = list(find_iban("IBAN: NO8010000000006"))
        assert len(f) == 1
        assert f[0].category == "IBAN"

    def test_gb_iban(self):
        f = list(find_iban("GB29 NWBK 6016 1331 9268 19"))
        assert len(f) == 1
        assert f[0].category == "IBAN"

    def test_se_iban(self):
        f = list(find_iban("SE7450000000001234567890"))
        assert len(f) == 1

    def test_invalid_checksum(self):
        f = list(find_iban("NO0010000000006"))  # feil sjekksiffer
        assert f == []

    def test_unknown_country_not_matched(self):
        f = list(find_iban("XX9900000000000000"))
        assert f == []

    def test_masked_display(self):
        f = list(find_iban("NO8010000000006"))
        assert "…" in f[0].text  # IBAN skal maskeres


# ════════════════════════════════════════════════════════════
#  secrets
# ════════════════════════════════════════════════════════════

from xlent_scanner.detectors.secrets import detect_secrets, find_known_secrets


class TestSecrets:
    def test_openai_key(self):
        key = "sk-aBcDeFgHiJkLmNoPqRsTuVwXyZaBcDeFgHiJkLmNoPqRsTuV"
        f = detect_secrets(f"Nøkkel: {key}")
        cats = _cats(f)
        assert any("OpenAI" in c for c in cats)

    def test_aws_key(self):
        # AKIA + nøyaktig 16 store alfanum-tegn (standard AWS test-ID)
        f = detect_secrets("AWS: AKIAIOSFODNN7EXAMPLE")
        assert any("AWS" in c for c in _cats(f))

    def test_github_token(self):
        f = detect_secrets("GH: ghp_AbCdEfGhIjKlMnOpQrStUvWxYz1234567890Ab")
        assert any("GitHub" in c for c in _cats(f))

    def test_jwt(self):
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyMTIzIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        f = detect_secrets(jwt)
        assert any("JWT" in c for c in _cats(f))

    def test_passord_i_konfig(self):
        f = detect_secrets("password=hemmelig123abc")
        cats = _cats(f)
        assert any("Passord" in c or "passord" in c or "Konfig" in c or "konfig" in c or "konfigurasjons" in c.lower() for c in cats)

    def test_sensitive_is_masked(self):
        key = "sk-aBcDeFgHiJkLmNoPqRsTuVwXyZaBcDeFgHiJkLmNoPqRsTuV"
        f = detect_secrets(f"Key: {key}")
        for finding in f:
            assert key not in finding.text, "Fullt API-nøkkel skal ikke vises ukryptert"

    def test_no_false_positive_short(self):
        f = [f2 for f2 in detect_secrets("abc123") if "secret" in f2.category.lower() or "entropy" in f2.category.lower()]
        assert f == []


# ════════════════════════════════════════════════════════════
#  financials
# ════════════════════════════════════════════════════════════

from xlent_scanner.detectors.financials import find_financial_data


class TestFinancials:
    def test_timepris_slash(self):
        f = list(find_financial_data("Timepris: 1 850 kr/time"))
        cats = _cats(f)
        assert "timepris" in cats

    def test_dagspris_slash(self):
        f = list(find_financial_data("Sats: 14 800/dag"))
        cats = _cats(f)
        assert "dagspris" in cats

    def test_prosjektsum_kw(self):
        f = list(find_financial_data("Prosjektsum: 4 500 000 NOK"))
        cats = _cats(f)
        assert "prosjektsum" in cats

    def test_kontraktsverdi(self):
        f = list(find_financial_data("kontraktsverdi: NOK 2 200 000"))
        cats = _cats(f)
        assert "prosjektsum" in cats

    def test_margin(self):
        f = list(find_financial_data("Margin: 35%"))
        cats = _cats(f)
        assert any("margin" in c for c in cats)

    def test_rabatt(self):
        f = list(find_financial_data("Rabatt: 5%"))
        cats = _cats(f)
        assert any("rabatt" in c for c in cats)

    def test_no_false_positive_without_keyword(self):
        """Kun et tall uten nøkkelord skal ikke flagges."""
        f = list(find_financial_data("Vi er 50 ansatte her."))
        assert f == []


# ════════════════════════════════════════════════════════════
#  keywords
# ════════════════════════════════════════════════════════════

from xlent_scanner.detectors.keywords import find_confidential_markers


class TestKeywords:
    def test_konfidensielt_heading(self):
        f = list(find_confidential_markers("# Strengt konfidensielt"))
        assert any("overskrift" in x.category for x in f)

    def test_konfidensielt_body(self):
        f = list(find_confidential_markers("Dette er konfidensielt."))
        assert any("brødtekst" in x.category or "konfidensielt dokument" in x.category for x in f)

    def test_nda(self):
        f = list(find_confidential_markers("Partene er bundet av NDA."))
        assert any("konfidensielt" in x.category.lower() for x in f)

    def test_api_key_code_word(self):
        f = list(find_confidential_markers("Sett api_key=verdi"))
        cats = _cats(f)
        assert any("konfigurasjons" in c.lower() for c in cats)

    def test_database_url(self):
        f = list(find_confidential_markers("database_url=postgres://..."))
        cats = _cats(f)
        assert any("konfigurasjons" in c.lower() for c in cats)

    def test_no_false_positive(self):
        f = list(find_confidential_markers("Normal tekst uten sensitivt innhold."))
        assert f == []


# ════════════════════════════════════════════════════════════
#  regex_url
# ════════════════════════════════════════════════════════════

from xlent_scanner.detectors.regex_url import detect_urls


class TestUrls:
    def test_https(self):
        f = list(detect_urls("Se https://portal.nordea.com/prosjekt"))
        texts = _texts(f)
        assert any("portal.nordea.com" in t for t in texts)

    def test_http(self):
        f = list(detect_urls("http://intern.xlent.no/wiki"))
        assert len(f) == 1

    def test_www(self):
        f = list(detect_urls("Gå til www.xlent.no/intern"))
        texts = _texts(f)
        assert any("www.xlent.no" in t for t in texts)

    def test_email_not_caught(self):
        f = list(detect_urls("test@example.com"))
        texts = _texts(f)
        assert not any("@" in t for t in texts)

    def test_bare_domain_not_caught(self):
        f = list(detect_urls("xlent.no"))
        texts = _texts(f)
        assert not any("xlent.no" in t for t in texts)

    def test_deduplication(self):
        f = list(detect_urls("https://example.com og https://example.com"))
        assert len(f) == 1

    def test_trailing_punctuation_stripped(self):
        f = list(detect_urls("Se https://example.com."))
        assert all(not t.endswith(".") for t in _texts(f))
