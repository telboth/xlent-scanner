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
