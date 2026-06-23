from xlent_scanner.detectors.ner_names import looks_like_person_name


def test_person_name_filter_accepts_real_names():
    assert looks_like_person_name("Thomas Elboth")
    assert looks_like_person_name("Anne-Marie Hansen")
    assert looks_like_person_name("Per Erik Hansen")
    assert looks_like_person_name("Susanne Rentch-Smith")


def test_person_name_filter_rejects_roles_and_lowercase_words():
    for value in [
        "brukeren",
        "veilederen",
        "brukere",
        "saksbehandlere",
        "saksbehandler",
    ]:
        assert not looks_like_person_name(value)


def test_person_name_filter_rejects_organizations_agencies_and_lists():
    for value in [
        "Visma, Tieto og Oslo kommunes Fasit-team",
        "Arbeids- og velferdsdirektoratet, KS, Trondheim Digital og DigiRogland",
        "Oslo kommunes Fasit-team",
        "Arbeids- og velferdsdirektoratet",
        "Trondheim Digital",
        "DigiRogland",
    ]:
        assert not looks_like_person_name(value)
