from xlent_scanner.detectors.ner_names import (
    looks_like_person_name,
    looks_like_person_name_in_context,
)


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


def test_person_name_filter_rejects_generic_technical_title_case_phrases():
    for value in [
        "Signal Processing",
        "Literature Review",
        "Case Study",
        "Software Architecture",
        "Training Dataset",
        "Survey Design",
        "Parameter Estimate",
        "Sensitivity Analysis",
        "Baseline Scenario",
        "Quality Assurance",
        "Risk Assessment",
        "Project Plan",
        "Appendix Figure",
        "Method Description",
        "Result Summary",
        "Petroleum Geoscience",
        "Master Thesis",
        "Seismic Interpretation",
        "Reservoir Model",
        "Uncertainty Analysis",
        "Batch Size",
        "Machine Intelligence",
        "Machine Intelligense",
        "Machine Learning",
        "Artificial Intelligence",
        "Physically Informed Autoencoder",
        "Cyclic Thin Interbeds",
        "Spec-Driven Development",
        "Conversion Tool",
        "Frequency Range",
        "Line Total",
        "Net Amount",
        "VAT Amount",
        "Invoice Total",
        "Quantity Description",
        "Discount Amount",
    ]:
        assert not looks_like_person_name(value)


def test_person_name_context_filter_rejects_academic_references():
    text = "Dette er omtalt av Susanne Rentch-Smith et al. (2024), doi: 10.1234/example."
    start = text.index("Susanne")
    end = start + len("Susanne Rentch-Smith")

    assert looks_like_person_name("Susanne Rentch-Smith")
    assert not looks_like_person_name_in_context("Susanne Rentch-Smith", text, start, end)


def test_person_name_context_filter_rejects_bibliographic_lines():
    text = "References: Thomas Elboth and Kari Hansen, ISBN 978-82-123456-7-8."
    start = text.index("Thomas")
    end = start + len("Thomas Elboth")

    assert looks_like_person_name("Thomas Elboth")
    assert not looks_like_person_name_in_context("Thomas Elboth", text, start, end)


def test_person_name_context_filter_rejects_geoscience_field_names():
    text = (
        "The text discusses the Sleipner Vest gas field and the "
        "Sleipner Øst condensate field."
    )
    for name in ("Sleipner Vest", "Sleipner Øst"):
        start = text.index(name)
        end = start + len(name)

        assert looks_like_person_name(name)
        assert not looks_like_person_name_in_context(name, text, start, end)


def test_person_name_context_filter_keeps_normal_sentence_names():
    text = "Rapporten ble skrevet av Thomas Elboth etter intervjuet."
    start = text.index("Thomas")
    end = start + len("Thomas Elboth")

    assert looks_like_person_name_in_context("Thomas Elboth", text, start, end)
