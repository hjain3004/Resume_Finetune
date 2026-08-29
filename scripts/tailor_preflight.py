"""Model-free tailoring preflight CLI. Prints every finding from
src.tailor.preflight.run_preflight and exits non-zero on any failure -- run
this before spending a single model call."""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from src.tailor.preflight import run_preflight


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scripts.tailor_preflight")
    parser.add_argument("--profile", default="config/master_profile.yaml")
    parser.add_argument("--template", default="profile/template.tex")
    parser.add_argument("--prompts", default="docs/prompts")
    parser.add_argument("--workdir")
    parser.add_argument("--skip-render", action="store_true")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(args.workdir) if args.workdir else Path(tmp)
        report = run_preflight(
            Path(args.profile), Path(args.template), Path(args.prompts), workdir,
            skip_render=args.skip_render,
        )
    if not report.findings:
        print("preflight: PASS (0 findings)")
        return 0
    for finding in report.findings:
        print(f"preflight [{finding.check}] {finding.surface}: {finding.message}", file=sys.stderr)
    print(f"preflight: FAIL ({len(report.findings)} finding(s))", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
