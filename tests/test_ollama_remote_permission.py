import json

import pytest

from xlent_scanner import deep_scanner


@pytest.mark.parametrize(
    "base_url",
    (
        "http://localhost:11434",
        "http://localhost.:11434",
        "http://127.0.0.1:11434",
        "http://127.42.0.1:11434",
        "http://[::1]:11434",
    ),
)
def test_local_ollama_does_not_require_remote_permission(monkeypatch, base_url):
    monkeypatch.delenv("XLENT_SCANNER_ALLOW_REMOTE_OLLAMA", raising=False)

    deep_scanner._require_ollama_connection_permission(base_url)


def test_remote_ollama_is_blocked_before_network_call(monkeypatch):
    monkeypatch.setattr(deep_scanner, "OLLAMA_BASE", "http://192.168.1.10:11434")
    monkeypatch.delenv("XLENT_SCANNER_ALLOW_REMOTE_OLLAMA", raising=False)
    monkeypatch.setattr(
        deep_scanner.urllib.request,
        "urlopen",
        lambda *args, **kwargs: pytest.fail("Remote Ollama must not be contacted"),
    )

    with pytest.raises(PermissionError, match="XLENT_SCANNER_ALLOW_REMOTE_OLLAMA=true"):
        deep_scanner._post("/api/generate", {"prompt": "sensitive text"})


def test_ollama_status_explains_missing_remote_permission(monkeypatch):
    monkeypatch.setattr(deep_scanner, "OLLAMA_BASE", "http://ollama.internal:11434")
    monkeypatch.delenv("XLENT_SCANNER_ALLOW_REMOTE_OLLAMA", raising=False)

    status = deep_scanner.ollama_status()

    assert status["running"] is False
    assert "XLENT_SCANNER_ALLOW_REMOTE_OLLAMA=true" in status["error"]


def test_remote_ollama_requires_explicit_truthy_permission(monkeypatch):
    monkeypatch.setattr(deep_scanner, "OLLAMA_BASE", "https://ollama.example.test")
    monkeypatch.setenv("XLENT_SCANNER_ALLOW_REMOTE_OLLAMA", "true")
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({"models": []}).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr(deep_scanner.urllib.request, "urlopen", fake_urlopen)

    assert deep_scanner._get("/api/tags") == {"models": []}
    assert captured == {
        "url": "https://ollama.example.test/api/tags",
        "timeout": 5,
    }


@pytest.mark.parametrize("permission", ("", "0", "false", "no"))
def test_remote_ollama_rejects_non_truthy_permission(monkeypatch, permission):
    monkeypatch.setenv("XLENT_SCANNER_ALLOW_REMOTE_OLLAMA", permission)

    with pytest.raises(PermissionError):
        deep_scanner._require_ollama_connection_permission(
            "http://ollama.example.test:11434"
        )


@pytest.mark.parametrize("base_url", ("ollama.internal:11434", "file:///tmp/ollama"))
def test_invalid_ollama_url_is_rejected_even_with_permission(monkeypatch, base_url):
    monkeypatch.setenv("XLENT_SCANNER_ALLOW_REMOTE_OLLAMA", "true")

    with pytest.raises(ValueError, match="HTTP- eller HTTPS-adresse"):
        deep_scanner._require_ollama_connection_permission(base_url)
