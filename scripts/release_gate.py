from __future__ import annotations

import argparse
from pathlib import Path


def _one(pattern: str) -> Path:
    matches = sorted(Path().glob(pattern))
    if len(matches) != 1:
        raise RuntimeError(f"Expected exactly one match for {pattern!r}, found {len(matches)}")
    if matches[0].stat().st_size <= 0:
        raise RuntimeError(f"Artifact is empty: {matches[0]}")
    return matches[0]


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate release artifacts before upload.")
    parser.add_argument("--platform", choices=["windows", "macos", "linux"], required=True)
    args = parser.parse_args()

    if args.platform == "windows":
        artifact = _one("artifacts/windows/installer/*.exe")
        script = Path("scripts/install_windows.ps1")
    elif args.platform == "macos":
        artifact = _one("artifacts/macos/installer/*.dmg")
        script = Path("scripts/install_macos.sh")
    else:
        artifact = _one("artifacts/linux/installer/xlent-scanner-linux-*.AppImage")
        script = None

    if script is not None and (not script.exists() or script.stat().st_size <= 0):
        raise RuntimeError(f"Install script missing or empty: {script}")

    print(f"release gate ok: {args.platform} -> {artifact}")


if __name__ == "__main__":
    main()
