from pathlib import Path

import pytest

from scripts import release_preflight


def _write_versions(root: Path, versions: tuple[str, str, str]) -> None:
    pyproject, init, lock = versions
    (root / "src/xlent_scanner").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "xlent-scanner"\nversion = "{pyproject}"\n',
        encoding="utf-8",
    )
    (root / "src/xlent_scanner/__init__.py").write_text(
        f'__version__ = "{init}"\n',
        encoding="utf-8",
    )
    (root / "uv.lock").write_text(
        f'[[package]]\nname = "xlent-scanner"\nversion = "{lock}"\n',
        encoding="utf-8",
    )


def test_read_versions_requires_all_release_files_to_match(tmp_path: Path) -> None:
    _write_versions(tmp_path, ("1.5.5", "1.5.5", "1.5.4"))

    versions = release_preflight.read_versions(tmp_path)

    assert versions["pyproject.toml"] == "1.5.5"
    assert versions["uv.lock"] == "1.5.4"


def test_validate_release_rejects_version_mismatch(monkeypatch, tmp_path: Path) -> None:
    _write_versions(tmp_path, ("1.5.5", "1.5.5", "1.5.4"))

    with pytest.raises(release_preflight.ReleasePreflightError, match="samsvarer ikke"):
        release_preflight.validate_release(
            tmp_path,
            version="1.5.5",
            tag="v1.5.5",
        )


def test_validate_release_rejects_wrong_tag(monkeypatch, tmp_path: Path) -> None:
    _write_versions(tmp_path, ("1.5.5", "1.5.5", "1.5.5"))

    with pytest.raises(release_preflight.ReleasePreflightError, match="Tag må være"):
        release_preflight.validate_release(
            tmp_path,
            version="1.5.5",
            tag="release-1.5.5",
        )


def test_validate_release_requires_release_branch(monkeypatch, tmp_path: Path) -> None:
    _write_versions(tmp_path, ("1.5.5", "1.5.5", "1.5.5"))

    def fake_git(repo, *args, check=True):
        if args == ("branch", "--show-current"):
            return "feature"
        raise AssertionError(args)

    monkeypatch.setattr(release_preflight, "_git", fake_git)

    with pytest.raises(release_preflight.ReleasePreflightError, match="master"):
        release_preflight.validate_release(
            tmp_path,
            version="1.5.5",
            tag="v1.5.5",
        )


def test_validate_release_requires_head_to_match_origin(monkeypatch, tmp_path: Path) -> None:
    _write_versions(tmp_path, ("1.5.5", "1.5.5", "1.5.5"))

    def fake_git(repo, *args, check=True):
        values = {
            ("branch", "--show-current"): "master",
            ("status", "--porcelain"): "",
            ("rev-parse", "HEAD"): "a" * 40,
            ("rev-parse", "--verify", "refs/remotes/origin/master"): "b" * 40,
        }
        if args in values:
            return values[args]
        raise AssertionError(args)

    monkeypatch.setattr(release_preflight, "_git", fake_git)

    with pytest.raises(release_preflight.ReleasePreflightError, match="ikke identisk"):
        release_preflight.validate_release(
            tmp_path,
            version="1.5.5",
            tag="v1.5.5",
        )


def test_allow_ahead_still_rejects_diverged_branch(monkeypatch, tmp_path: Path) -> None:
    _write_versions(tmp_path, ("1.5.5", "1.5.5", "1.5.5"))

    def fake_git(repo, *args, check=True):
        values = {
            ("branch", "--show-current"): "master",
            ("status", "--porcelain"): "",
            ("rev-parse", "HEAD"): "a" * 40,
            ("rev-parse", "--verify", "refs/remotes/origin/master"): "b" * 40,
        }
        if args in values:
            return values[args]
        raise AssertionError(args)

    monkeypatch.setattr(release_preflight, "_git", fake_git)
    monkeypatch.setattr(release_preflight, "_git_ok", lambda *args: False)

    with pytest.raises(release_preflight.ReleasePreflightError, match="divergert"):
        release_preflight.validate_release(
            tmp_path,
            version="1.5.5",
            tag="v1.5.5",
            require_remote_sync=False,
        )
