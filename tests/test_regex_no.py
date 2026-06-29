"""Unit-tester for norske regex-detektorer (regex_no.py)."""
from __future__ import annotations

import pytest
from xlent_scanner.detectors.regex_no import (
    find_emails,
    find_fnr,
    find_kontonummer,
    find_orgnr,
    find_telefon,
)


# ── E-post ────────────────────────────────────────────────────────────────────

class TestFindEmails:
    def _hits(self, text: str) -> list[str]:
        return [f.text for f in find_emails(text)]

    def test_simple(self):
        assert "thomas@xlent.no" in self._hits("Send til thomas@xlent.no i dag.")

    def test_gmail(self):
        assert "t.elboth@gmail.com" in self._hits("Privat: t.elboth@gmail.com")

    def test_plus_tag(self):
        assert "user.name+tag@example.co.uk" in self._hits("user.name+tag@example.co.uk")

    def test_no_false_positive_url(self):
        assert not self._hits("Gå til https://www.xlent.no for mer info.")

    def test_multiple_emails(self):
        hits = self._hits("Thomas.elboth@xlent.no og t.elboth@gmail.com")
        assert len(hits) == 2


# ── Fødselsnummer og D-nummer ────────────────────────────────────────────────

class TestFindFnr:
    def _kinds(self, text: str) -> list[str]:
        return [f.category for f in find_fnr(text)]

    def _texts(self, text: str) -> list[str]:
        return [f.text for f in find_fnr(text)]

    # Gyldige fødselsnumre (mod-11 validerer)
    def test_valid_11digit(self):
        # 01019750023: beregnet gyldig FNR (dato 01.01.97, individnr 500)
        assert "fødselsnummer" in self._kinds("Fnr: 01019750023")

    def test_valid_with_space(self):
        # 010197 50023 – med mellomrom
        assert "fødselsnummer" in self._kinds("010197 50023")

    # Ugyldig mod-11 men gyldig datoformat → «mulig personnummer (format)»
    def test_invalid_checksum_gives_possible(self):
        # 21057212345 – ugyldig mod-11, men dag=21, mnd=05 er gyldig dato
        kinds = self._kinds("FNR: 21057212345")
        assert "mulig personnummer (format)" in kinds
        assert "fødselsnummer" not in kinds

    def test_invalid_space_format_gives_possible(self):
        # 210572 12345 – ugyldig mod-11
        kinds = self._kinds("FNR: 210572 12345")
        assert "mulig personnummer (format)" in kinds
        assert "fødselsnummer" not in kinds

    def test_invalid_date_gives_nothing(self):
        # dag=99 finnes ikke → skal ikke fanges overhodet
        assert not self._kinds("99131234567")

    # D-nummer
    def test_dnumber(self):
        # Bekreftet gyldig D-nummer (dag+40=41, mnd=01, år=90): 41019000077
        result = list(find_fnr("D-nr: 41019000077"))
        assert result, "Gyldig D-nummer skal gi ett funn"
        assert result[0].category == "d-nummer"


# ── Kontonummer ───────────────────────────────────────────────────────────────

class TestFindKontonummer:
    def _texts(self, text: str) -> list[str]:
        return [f.text for f in find_kontonummer(text)]

    # 1730.1777.922 – GYLDIG (bekreftet manuelt)
    def test_valid_dot_format(self):
        hits = self._texts("Konto: 1730.1777.922")
        assert hits, "Forventer treff på 1730.1777.922"

    # 17301777922 – GYLDIG (11 siffer rå)
    def test_valid_raw_11digit(self):
        hits = self._texts("Kontonr 17301777922")
        assert hits

    # 1730 1777 922 – GYLDIG (4-4-3 med mellomrom)
    def test_valid_space_format(self):
        hits = self._texts("Konto 1730 1777 922")
        assert hits

    # 1234 5678 910 – UGYLDIG (mod-11 feiler)
    def test_invalid_checksum(self):
        hits = self._texts("Konto: 1234 5678 910")
        assert not hits, f"Forventer INGEN treff på ugyldig konto, fikk: {hits}"

    # 12345678910 – UGYLDIG
    def test_invalid_raw_checksum(self):
        hits = self._texts("12345678910")
        assert not hits


# ── Organisasjonsnummer ───────────────────────────────────────────────────────

class TestFindOrgnr:
    def _texts(self, text: str) -> list[str]:
        return [f.text for f in find_orgnr(text)]

    # 974760673 – Statsministerens kontor (kjent gyldig)
    def test_valid_orgnr(self):
        assert self._texts("Org.nr 974 760 673")

    def test_valid_no_spaces(self):
        assert self._texts("974760673")

    # 123456789 – starter ikke med 8/9 → skal ikke matche
    def test_invalid_start_digit(self):
        assert not self._texts("123456789")

    # 987654320 – starter med 9, men mod-11 feiler (antagelig)
    def test_invalid_checksum(self):
        # Bruk et tall som starter med 9 men har feil kontrollsiffer
        assert not self._texts("900000001")


# ── Telefonnummer ─────────────────────────────────────────────────────────────

class TestFindTelefon:
    def _texts(self, text: str) -> list[str]:
        return [f.text for f in find_telefon(text)]

    def test_8digit_mobile(self):
        assert self._texts("Ring 91717680")

    def test_plus47(self):
        assert self._texts("+47 91717678")

    def test_plus47_no_space(self):
        assert self._texts("+4791717678")

    def test_0047_prefix(self):
        assert self._texts("0047 12345678")

    def test_0047_1prefix(self):
        # "0047 12345678" – 0047 + 8 siffer
        hits = self._texts("Faks: 0047 12345678")
        assert hits

    def test_formatted_spaces(self):
        assert self._texts("+47 917 17 678")

    # Falske positiver
    def test_year_not_matched(self):
        assert not self._texts("Rapport fra 2024.")

    def test_year_range_not_matched_as_phone(self):
        assert not self._texts("Avtaleperioden er 2025-2026.")

    def test_iso_date_not_matched_as_phone(self):
        assert not self._texts("Dato: 2021-03-09.")

    def test_meter_range_not_matched_as_phone(self):
        assert not self._texts("Dybdeintervallet er 3000-4500m.")

    def test_chart_axis_values_not_matched_as_phone(self):
        text = (
            "Time domain error 0 5 10 15 20 25 30 35 40 45 50 55 "
            "60 65 70 75 80 85 90 95 100 105 110 115 Frequency gap [Hz]"
        )

        hits = self._texts(text)

        assert "20 25 30 35" not in hits
        assert "40 45 50 55" not in hits
        assert "70 75 80 85" not in hits
        assert hits == []

    def test_large_chart_axis_values_not_matched_as_phone(self):
        text = "Target 0 1000 2000 3000 4000 O,set [m] 0 1 2 3 4 Time [s]"

        assert "2000 3000" not in self._texts(text)
        assert self._texts(text) == []

    def test_frequency_axis_values_not_matched_as_phone(self):
        text = "Frequency gap [Hz] 0 10 20 30 40 50 60 Error [degrees]"

        assert "20 30 40 50" not in self._texts(text)
        assert self._texts(text) == []

    def test_regular_phone_number_with_spaces_is_still_matched(self):
        assert "22 33 44 55" in self._texts("Ring sentralbordet på 22 33 44 55.")

    def test_explicit_phone_label_overrides_axis_like_number_sequence(self):
        assert "20 25 30 35" in self._texts("Tel: 20 25 30 35")

    def test_page_range_not_matched_as_phone(self):
        assert not self._texts("Dette er omtalt i Smith et al., pp. 4662-4666.")

    def test_pages_label_not_matched_as_phone(self):
        assert not self._texts("See pages 4662-4666 for details.")

    def test_phone_label_still_allows_same_digit_pattern_as_page_range(self):
        assert "4662-4666" in self._texts("Tel: 4662-4666")

    def test_postcode_not_matched(self):
        assert not self._texts("Postnummer: 0150")
