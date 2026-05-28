"""Unit-tester for svenske regex-detektorer (regex_sv.py)."""
from __future__ import annotations

import pytest
from xlent_scanner.detectors.regex_sv import (
    find_persnr,
    find_orgnr_sv,
    find_telefon_sv,
    find_bankgiro,
    find_plusgiro,
)


class TestFindPersnr:
    def _cats(self, text: str) -> list[str]:
        return [f.category for f in find_persnr(text)]

    def test_known_valid_persnr(self):
        # 811228-9874 – kjent gyldig test-personnummer (Luhn mod-10)
        cats = self._cats("Personnummer: 811228-9874")
        assert "personnummer (SV)" in cats

    def test_12digit_format(self):
        cats = self._cats("19811228-9874")
        assert "personnummer (SV)" in cats

    def test_samordningsnummer(self):
        # Samordningsnummer: dag + 60 = dag 61-91
        # 640364-5002: dato 1964-03-04 + samnr-offset 60 → dag=64, Luhn-validert
        cats = self._cats("640364-5002")
        assert "samordningsnummer (SV)" in cats

    def test_invalid_checksum(self):
        # 811228-9875 – siste siffer endret → Luhn feiler
        assert not self._cats("811228-9875")


class TestFindOrgnrSv:
    def _texts(self, text: str) -> list[str]:
        return [f.text for f in find_orgnr_sv(text)]

    def test_valid_orgnr(self):
        # 556036-0793 – Volvo AB (kjent gyldig)
        assert self._texts("Org: 556036-0793")

    def test_invalid_siffra2(self):
        # Siffra[2] < 2 → behandles som personnummer, ikke org-nummer
        assert not self._texts("010101-1234")


class TestFindTelefonSv:
    def _texts(self, text: str) -> list[str]:
        return [f.text for f in find_telefon_sv(text)]

    def test_mobile(self):
        assert self._texts("Mobil: 070-123 45 67")

    def test_plus46(self):
        assert self._texts("+46 70 123 45 67")

    def test_stockholm(self):
        assert self._texts("08-123 45 67")


class TestFindBankgiro:
    def _texts(self, text: str) -> list[str]:
        return [f.text for f in find_bankgiro(text)]

    def test_bankgiro_with_keyword(self):
        assert self._texts("Bankgiro: 123-4567")

    def test_no_keyword_no_match(self):
        # Uten nøkkelord – skal ikke matche
        assert not self._texts("Konto 1234567")
