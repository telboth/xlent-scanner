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
