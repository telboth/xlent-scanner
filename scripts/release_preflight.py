"""Valider release-branch, versjonsfiler og tag-target før publisering."""
from __future__ import annotations

import argparse
import re
import subprocess
import tomllib
from pathlib import Path


class ReleasePreflightError(RuntimeError):
    pass


def _git(repo: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        raise ReleasePreflightError(
            f"git {' '.join(args)} feilet: {(result.stderr or result.stdout).strip()}"
        )
    return result.stdout.strip() if result.returncode == 0 else ""


def _git_ok(repo: Path, *args: str) -> bool:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    ).returncode == 0


def read_versions(repo: Path) -> dict[str, str]:
    with (repo / "pyproject.toml").open("rb") as fh:
        pyproject_version = str(tomllib.load(fh)["project"]["version"])

    init_text = (repo / "src/xlent_scanner/__init__.py").read_text(encoding="utf-8")
    init_match = re.search(r'__version__\s*=\s*"([^"]+)"', init_text)
    if not init_match:
        raise ReleasePreflightError("Fant ikke __version__ i src/xlent_scanner/__init__.py.")

    with (repo / "uv.lock").open("rb") as fh:
        lock_data = tomllib.load(fh)
    lock_versions = [
        str(package["version"])
        for package in lock_data.get("package", [])
        if package.get("name") == "xlent-scanner"
    ]
    if len(lock_versions) != 1:
        raise ReleasePreflightError("Fant ikke entydig xlent-scanner-versjon i uv.lock.")

    return {
        "pyproject.toml": pyproject_version,
        "src/xlent_scanner/__init__.py": init_match.group(1),
        "uv.lock": lock_versions[0],
    }


def validate_release(
    repo: Path,
    *,
    version: str,
    tag: str,
    release_branch: str = "master",
    require_remote_sync: bool = True,
) -> str:
    versions = read_versions(repo)
    mismatches = {path: value for path, value in versions.items() if value != version}
    if mismatches:
        details = ", ".join(f"{path}={value}" for path, value in mismatches.items())
        raise ReleasePreflightError(
            f"Versjonsfilene samsvarer ikke med {version}: {details}"
        )

    expected_tag = f"v{version}"
    if tag != expected_tag:
        raise ReleasePreflightError(f"Tag må være {expected_tag}, ikke {tag}.")

    branch = _git(repo, "branch", "--show-current")
    if branch != release_branch:
        raise ReleasePreflightError(
            f"Release må kjøres fra {release_branch}; aktiv branch er {branch or '(detached)' }."
        )

    if _git(repo, "status", "--porcelain"):
        raise ReleasePreflightError("Arbeidstreet er ikke rent.")

    head = _git(repo, "rev-parse", "HEAD")
    remote_ref = f"refs/remotes/origin/{release_branch}"
    remote_head = _git(repo, "rev-parse", "--verify", remote_ref, check=False)
    if not remote_head:
        raise ReleasePreflightError(f"Fant ikke {remote_ref}; kjør git fetch origin.")
    if require_remote_sync and head != remote_head:
        raise ReleasePreflightError(
            f"HEAD ({head[:8]}) er ikke identisk med origin/{release_branch} ({remote_head[:8]})."
        )
    if (
        not require_remote_sync
        and head != remote_head
        and not _git_ok(repo, "merge-base", "--is-ancestor", remote_ref, "HEAD")
    ):
        raise ReleasePreflightError(
            f"HEAD er bak eller har divergert fra origin/{release_branch}; "
            "oppdater branchen før release."
        )

    tag_target = _git(repo, "rev-parse", "--verify", f"refs/tags/{tag}^{{}}", check=False)
    if tag_target and tag_target != head:
        raise ReleasePreflightError(
            f"Eksisterende tag {tag} peker på {tag_target[:8]}, ikke HEAD {head[:8]}."
        )
    return head


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--version", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--release-branch", default="master")
    parser.add_argument("--allow-ahead", action="store_true")
    args = parser.parse_args()

    try:
        head = validate_release(
            args.repo.resolve(),
            version=args.version,
            tag=args.tag,
            release_branch=args.release_branch,
            require_remote_sync=not args.allow_ahead,
        )
    except ReleasePreflightError as exc:
        print(f"Release preflight feilet: {exc}")
        return 1

    print(f"Release preflight OK: {args.tag} -> {head}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
