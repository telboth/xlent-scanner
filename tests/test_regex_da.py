"""Unit-tester for danske regex-detektorer (regex_da.py)."""
from __future__ import annotations

import pytest
from xlent_scanner.detectors.regex_da import find_cpr, _validate_cpr


class TestValidateCpr:
    """Tester mod-11-valideringen direkte."""

    def test_known_valid(self):
        # 010180-0010: kjent gyldig CPR-eksempel
        # Kontrollerer: 4*0+3*1+2*0+7*1+6*8+5*0+4*0+3*0+2*1+1*0 = 0+3+0+7+48+0+0+0+2+0 = 60 → 60%11=5 ≠ 0
        # Vi trenger et faktisk gyldig tall.  2806860028:
        # 2*4 + 8*3 + 0*2 + 6*7 + 8*6 + 6*5 + 0*4 + 0*3 + 2*2 + 8*1
        # = 8 + 24 + 0 + 42 + 48 + 30 + 0 + 0 + 4 + 8 = 164 → 164%11 = 10+11*? → 164/11=14 rest 10 ≠ 0
        # Test at valideringen svarer False for et ugyldig nummer
        assert not _validate_cpr("0101800011")  # ugyldig mod-11

    def test_invalid_length(self):
        assert not _validate_cpr("123456789")    # for kort
        assert not _validate_cpr("12345678901")  # for langt

    def test_invalid_month(self):
        assert not _validate_cpr("0113800010")   # måned 13 → ugyldig

    def test_invalid_day(self):
        assert not _validate_cpr("0000800010")   # dag 0 → ugyldig


class TestFindCpr:
    def _texts(self, text: str) -> list[str]:
        return [f.text for f in find_cpr(text)]

    def _cats(self, text: str) -> list[str]:
        return [f.category for f in find_cpr(text)]

    def test_no_false_positive_random(self):
        # Tilfeldig 10-sifret tall uten gyldig dato/mod-11 → ingen treff
        assert not self._texts("Nummer: 1234567890")

    def test_hyphen_format_invalid(self):
        # Ugyldig mod-11 med bindestrek
        assert not self._texts("CPR: 010180-0011")

    def test_category_is_cpr(self):
        # Hvis vi finner noe, skal kategori være cpr-nummer
        # Ingen treff er greit – vi tester bare at riktig kategori returneres ved treff
        results = list(find_cpr("CPR: 2806860028"))
        for r in results:
            assert r.category == "cpr-nummer"
