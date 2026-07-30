"""Validate config/master_profile.yaml against the M8 loader.

Usage: python -m scripts.validate_profile [PATH]
Exit codes: 0 valid, 1 validation error, 2 file unreadable.
"""

from __future__ import annotations

import argparse
import sys

from src.profile import ProfileValidationError, load_profile

_DEFAULT_PATH = "config/master_profile.yaml"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the master profile.")
    parser.add_argument("path", nargs="?", default=_DEFAULT_PATH)
    args = parser.parse_args(argv)

    try:
        profile = load_profile(args.path)
    except ProfileValidationError as exc:
        print(f"INVALID {args.path}: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"UNREADABLE {args.path}: {exc}", file=sys.stderr)
        return 2

    sources = (*profile.projects, *profile.experience)
    bullets = sum(len(source.bullets) for source in sources)
    blocked = sum(
        1 for source in sources for bullet in source.bullets if bullet.is_blocked
    )
    print(
        f"OK {args.path}: schema {profile.schema_version}, "
        f"{len(profile.projects)} project(s), {len(profile.experience)} experience "
        f"entry(ies), {bullets} bullet(s) ({blocked} blocked), "
        f"base_variants: {', '.join(sorted(profile.base_variants)) or '(none)'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
