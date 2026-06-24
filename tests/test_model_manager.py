from __future__ import annotations

import io
import stat
import threading
import types
import zipfile
from pathlib import Path

from xlent_scanner import model_manager


class _Response:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        self._stream = io.BytesIO(self._data)
        return self

    def __exit__(self, *_args):
        return None

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)


def _wheel_bytes(entries: list[tuple[str, bytes, int | None]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content, mode in entries:
            info = zipfile.ZipInfo(name)
            if mode is not None:
                info.create_system = 3
                info.external_attr = mode << 16
            archive.writestr(info, content)
    return buffer.getvalue()


def _patch_download(monkeypatch, tmp_path: Path, archive: bytes) -> Path:
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    monkeypatch.setattr(model_manager, "_models_dir", lambda: models_dir)
    monkeypatch.setattr(
        model_manager.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _Response(archive),
    )
    model_manager._progress.clear()
    model_manager._active_downloads.clear()
    return models_dir


def test_model_download_rejects_path_traversal(monkeypatch, tmp_path):
    model = "nb_core_news_sm"
    prefix = f"{model}/{model}-3.8.0"
    archive = _wheel_bytes([
        (f"{prefix}/../../escaped.txt", b"escaped", None),
        (f"{prefix}/config.cfg", b"config", None),
        (f"{prefix}/meta.json", b"{}", None),
    ])
    models_dir = _patch_download(monkeypatch, tmp_path, archive)

    model_manager._download_model(model)

    assert not (tmp_path / "escaped.txt").exists()
    assert not (models_dir / model).exists()
    assert model_manager._progress[model].startswith("error:")


def test_model_download_rejects_symlink(monkeypatch, tmp_path):
    model = "nb_core_news_sm"
    prefix = f"{model}/{model}-3.8.0"
    archive = _wheel_bytes([
        (f"{prefix}/config.cfg", b"config", None),
        (f"{prefix}/meta.json", b"{}", None),
        (f"{prefix}/link", b"target", stat.S_IFLNK | 0o777),
    ])
    models_dir = _patch_download(monkeypatch, tmp_path, archive)

    model_manager._download_model(model)

    assert not (models_dir / model).exists()
    assert "Symbolsk lenke" in model_manager._progress[model]


def test_model_download_installs_valid_archive(monkeypatch, tmp_path):
    model = "nb_core_news_sm"
    prefix = f"{model}/{model}-3.8.0"
    archive = _wheel_bytes([
        (f"{prefix}/config.cfg", b"config", None),
        (f"{prefix}/meta.json", b"{}", None),
        (f"{prefix}/tokenizer", b"data", None),
    ])
    models_dir = _patch_download(monkeypatch, tmp_path, archive)

    model_manager._download_model(model)

    assert (models_dir / model / "config.cfg").is_file()
    assert (models_dir / model / "meta.json").is_file()
    assert model_manager._progress[model] == "done"


def test_model_download_start_is_atomic(monkeypatch):
    class DummyThread:
        def __init__(self, *_args, **_kwargs):
            pass

        def start(self):
            pass

    monkeypatch.setattr(model_manager, "threading", types.SimpleNamespace(Thread=DummyThread))
    model_manager._progress.clear()
    model_manager._active_downloads.clear()

    barrier = threading.Barrier(2)
    results: list[bool] = []

    def start_download() -> None:
        barrier.wait()
        results.append(model_manager.download_model_async("nb_core_news_sm"))

    threads = [threading.Thread(target=start_download) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(results) == [False, True]
    model_manager._active_downloads.clear()
