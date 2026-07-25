"""Fail a release build unless its Git tag exactly matches VERSION."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


VERSION_PATTERN = re.compile(r"\d+\.\d+\.\d+")


def read_version(version_file: Path) -> str:
    version = version_file.read_text(encoding="utf-8").strip()
    if not VERSION_PATTERN.fullmatch(version):
        raise ValueError(f"VERSION must contain exactly x.y.z digits, got {version!r}")
    return version


def verify_release_tag(tag: str, version: str) -> None:
    expected = f"v{version}"
    if tag != expected:
        raise ValueError(f"Release tag {tag!r} does not match VERSION; expected {expected!r}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True, help="Git tag name, including the leading v")
    parser.add_argument(
        "--version-file",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "VERSION",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        verify_release_tag(args.tag, read_version(args.version_file))
    except (OSError, ValueError) as exc:
        print(f"release validation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
