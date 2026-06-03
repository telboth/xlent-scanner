import time

from xlent_scanner import deep_scanner


def test_stop_ollama_model_unloads_without_stopping_service(monkeypatch):
    calls = []

    def fake_post(path, data, timeout=180):
        calls.append((path, data, timeout))
        return {"done": True}

    monkeypatch.setattr(deep_scanner, "_post", fake_post)

    result = deep_scanner.stop_ollama_model("llama3.2:3b")

    assert result == {"ok": True, "model": "llama3.2:3b"}
    assert calls == [
        (
            "/api/generate",
            {
                "model": "llama3.2:3b",
                "prompt": "",
                "stream": False,
                "keep_alive": 0,
            },
            30,
        )
    ]


def test_stop_ollama_model_requires_model_name():
    result = deep_scanner.stop_ollama_model("")

    assert result["ok"] is False
    assert "error" in result


def test_deep_scan_status_is_isolated_per_job(monkeypatch):
    monkeypatch.setattr(deep_scanner, "_call_ollama", lambda model, prompt: [])
    deep_scanner._jobs.clear()
    deep_scanner._job = {}

    first = deep_scanner.start_deep_scan("tekst en", "llama3.2:3b")
    second = deep_scanner.start_deep_scan("tekst to", "llama3.2:3b")

    assert first != second
    assert deep_scanner.get_deep_scan_status(first)["job_id"] == first
    assert deep_scanner.get_deep_scan_status(second)["job_id"] == second
    assert deep_scanner.get_deep_scan_status()["job_id"] == second

    deep_scanner.cancel_deep_scan(first)
    assert deep_scanner.get_deep_scan_status(first)["status"] == "cancelled"


def test_pull_ollama_model_tracks_status(monkeypatch):
    calls = []

    def fake_post(path, data, timeout=180):
        calls.append((path, data, timeout))
        return {"status": "success"}

    monkeypatch.setattr(deep_scanner, "_post", fake_post)
    deep_scanner._pull_job.clear()

    result = deep_scanner.pull_ollama_model("llama3.2:3b")

    assert result["ok"] is True
    assert result["model"] == "llama3.2:3b"
    deadline = time.monotonic() + 1
    while not calls and time.monotonic() < deadline:
        time.sleep(0.01)
    assert calls
    assert calls[0] == (
        "/api/pull",
        {"name": "llama3.2:3b", "stream": False},
        900,
    )


def test_deep_scan_ignores_email_domain_case_insensitive(monkeypatch):
    monkeypatch.setattr(
        deep_scanner,
        "_call_ollama",
        lambda model, prompt: [
            {
                "category": "E-post",
                "text": "Thomas.elboth@xlent.no",
                "context": "Kontakt Thomas.elboth@xlent.no",
                "confidence": "high",
            },
            {
                "category": "E-post",
                "text": "external@example.com",
                "context": "Kontakt external@example.com",
                "confidence": "high",
            },
        ],
    )
    deep_scanner._jobs.clear()
    deep_scanner._job = {}
    job_id = "ignore01"
    deep_scanner._jobs[job_id] = {
        "job_id": job_id,
        "status": "running",
        "progress": "",
        "findings": [],
        "cancelled": False,
        "started_at": time.time(),
    }

    deep_scanner._run_deep_scan(
        "Kontakt Thomas.elboth@xlent.no og external@example.com",
        "llama3.2:3b",
        "nb",
        job_id,
        ["epost"],
    )

    findings = deep_scanner.get_deep_scan_status(job_id)["findings"]
    texts = {f["text"] for f in findings}
    assert "Thomas.elboth@xlent.no" not in texts
    assert "external@example.com" in texts


def test_deep_scan_ignores_exact_email_case_insensitive(monkeypatch):
    monkeypatch.setattr(deep_scanner, "_call_ollama", lambda model, prompt: [])
    deep_scanner._jobs.clear()
    job_id = "ignore02"
    deep_scanner._jobs[job_id] = {
        "job_id": job_id,
        "status": "running",
        "progress": "",
        "findings": [],
        "cancelled": False,
        "started_at": time.time(),
    }

    from xlent_scanner import ignore  # noqa: PLC0415

    monkeypatch.setattr(
        ignore,
        "load_ignore_list",
        lambda: {"email_domains": [], "emails": ["thomas.elboth@xlent.no"], "names": []},
    )

    deep_scanner._run_deep_scan(
        "Kontakt Thomas.elboth@xlent.no og other@xlent.no",
        "llama3.2:3b",
        "nb",
        job_id,
        ["epost"],
    )

    texts = {f["text"] for f in deep_scanner.get_deep_scan_status(job_id)["findings"]}
    assert "Thomas.elboth@xlent.no" not in texts
    assert "other@xlent.no" in texts


def test_deep_scan_ignores_email_with_model_category_and_punctuation(monkeypatch):
    monkeypatch.setattr(
        deep_scanner,
        "_call_ollama",
        lambda model, prompt: [
            {
                "category": "e-postadresser",
                "text": "Thomas.elboth@xlent.no.",
                "context": "Kontakt: Thomas.elboth@xlent.no.",
                "confidence": "high",
            },
            {
                "category": "kontaktinformasjon",
                "text": "(Thomas.elboth@xlent.no)",
                "context": "Kontakt: (Thomas.elboth@xlent.no)",
                "confidence": "high",
            },
            {
                "category": "e-postadresser",
                "text": "external@example.com.",
                "context": "Kontakt: external@example.com.",
                "confidence": "high",
            },
        ],
    )
    deep_scanner._jobs.clear()
    job_id = "ignore03"
    deep_scanner._jobs[job_id] = {
        "job_id": job_id,
        "status": "running",
        "progress": "",
        "findings": [],
        "cancelled": False,
        "started_at": time.time(),
    }

    deep_scanner._run_deep_scan(
        "Kontakt Thomas.elboth@xlent.no og external@example.com",
        "llama3.2:3b",
        "nb",
        job_id,
        ["epost"],
    )

    texts = {f["text"] for f in deep_scanner.get_deep_scan_status(job_id)["findings"]}
    assert "Thomas.elboth@xlent.no." not in texts
    assert "(Thomas.elboth@xlent.no)" not in texts
    assert "external@example.com." in texts


def test_deep_scan_reclassifies_us_phone_misclassified_as_url(monkeypatch):
    monkeypatch.setattr(
        deep_scanner,
        "_call_ollama",
        lambda model, prompt: [
            {
                "category": "Nettadresse",
                "text": "(234) 567-8901",
                "context": "Call (234) 567-8901",
                "confidence": "high",
            },
            {
                "category": "URL",
                "text": "+01 (234) 567-4902",
                "context": "Call +01 (234) 567-4902",
                "confidence": "high",
            },
        ],
    )
    deep_scanner._jobs.clear()
    job_id = "phone01"
    deep_scanner._jobs[job_id] = {
        "job_id": job_id,
        "status": "running",
        "progress": "",
        "findings": [],
        "cancelled": False,
        "started_at": time.time(),
    }

    deep_scanner._run_deep_scan(
        "Call (234) 567-8901 or +01 (234) 567-4902",
        "llama3.2:3b",
        "en",
        job_id,
        ["telefon", "nettadresse"],
    )

    findings = deep_scanner.get_deep_scan_status(job_id)["findings"]
    assert len(findings) == 2
    assert {f["text"] for f in findings} == {"(234) 567-8901", "+01 (234) 567-4902"}
    assert all(f["category"] == "🤖 Telefonnummer" for f in findings)


def test_deep_scan_drops_us_phone_misclassified_as_url_when_phone_not_selected(monkeypatch):
    monkeypatch.setattr(
        deep_scanner,
        "_call_ollama",
        lambda model, prompt: [
            {
                "category": "Nettadresse",
                "text": "(234) 567-8901",
                "context": "Call (234) 567-8901",
                "confidence": "high",
            }
        ],
    )
    deep_scanner._jobs.clear()
    job_id = "phone02"
    deep_scanner._jobs[job_id] = {
        "job_id": job_id,
        "status": "running",
        "progress": "",
        "findings": [],
        "cancelled": False,
        "started_at": time.time(),
    }

    deep_scanner._run_deep_scan(
        "Call (234) 567-8901",
        "llama3.2:3b",
        "en",
        job_id,
        ["nettadresse"],
    )

    assert deep_scanner.get_deep_scan_status(job_id)["findings"] == []


def test_medical_category_is_opt_in_for_prompt():
    prompt_without = deep_scanner._build_prompt(["navn"], "Anne bruker Metformin.", "nb")
    default_prompt = deep_scanner._build_prompt([], "Anne bruker Metformin.", "nb")
    prompt_with = deep_scanner._build_prompt(["medisinsk"], "Anne bruker Metformin.", "nb")

    assert "medisinsk" not in deep_scanner.DEFAULT_CATEGORIES
    assert "medisinske opplysninger" not in prompt_without
    assert "medisinske opplysninger" not in default_prompt
    assert "Medisinsk informasjon" in prompt_with
    assert "sykdommer, diagnoser, symptomer" in prompt_with
    assert "Metformin" in prompt_with


def test_deep_scan_extracts_financial_numbers_from_budget_table(monkeypatch):
    monkeypatch.setattr(deep_scanner, "_call_ollama", lambda model, prompt: [])
    deep_scanner._jobs.clear()
    job_id = "fin01"
    deep_scanner._jobs[job_id] = {
        "job_id": job_id,
        "status": "running",
        "progress": "",
        "findings": [],
        "cancelled": False,
        "started_at": time.time(),
    }
    text = "\n".join([
        "Role | Hours | Cost (NOK) | Comment",
        "Architect | 12 | 30 | fixed",
        "Developer | 40 | 100 | fixed",
        "Tester | 8 | 2025-03-09 | date should not be cost",
    ])

    deep_scanner._run_deep_scan(text, "llama3.2:3b", "en", job_id, ["budsjett_tall"])

    findings = deep_scanner.get_deep_scan_status(job_id)["findings"]
    texts = {f["text"] for f in findings}
    assert {"30", "100"} <= texts
    assert "12" not in texts
    assert "40" not in texts
    assert "2025-03-09" not in texts
    assert all(f["category"] == "🤖 Budsjettall" for f in findings)


def test_deep_scan_does_not_extract_loose_or_non_financial_table_numbers(monkeypatch):
    monkeypatch.setattr(deep_scanner, "_call_ollama", lambda model, prompt: [])
    deep_scanner._jobs.clear()
    job_id = "fin02"
    deep_scanner._jobs[job_id] = {
        "job_id": job_id,
        "status": "running",
        "progress": "",
        "findings": [],
        "cancelled": False,
        "started_at": time.time(),
    }
    text = "\n".join([
        "We have 50 employees and 4-6 weeks timeline.",
        "Name | Hours | Quantity | Year",
        "Anne | 30 | 60 | 2026",
    ])

    deep_scanner._run_deep_scan(text, "llama3.2:3b", "en", job_id, ["budsjett_tall"])

    assert deep_scanner.get_deep_scan_status(job_id)["findings"] == []


def test_financial_table_supplement_only_runs_when_financial_category_selected(monkeypatch):
    monkeypatch.setattr(deep_scanner, "_call_ollama", lambda model, prompt: [])
    deep_scanner._jobs.clear()
    job_id = "fin03"
    deep_scanner._jobs[job_id] = {
        "job_id": job_id,
        "status": "running",
        "progress": "",
        "findings": [],
        "cancelled": False,
        "started_at": time.time(),
    }
    text = "Item | Cost (NOK)\nLicense | 100"

    deep_scanner._run_deep_scan(text, "llama3.2:3b", "en", job_id, ["navn"])

    assert deep_scanner.get_deep_scan_status(job_id)["findings"] == []
