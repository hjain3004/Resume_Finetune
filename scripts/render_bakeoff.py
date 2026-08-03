"""M10 bake-off: render both arms, run L7 on each, print a comparison.

Operator script. Visual acceptability is judged by the user, not by this script.
"""

import argparse
import logging
import sys
from pathlib import Path

from typing import Callable

from src.profile import load_profile
from src.render.model import RenderDoc
from src.render.l7 import run_l7
from src.render.mapping import build_render_doc
from src.render.parse import parse_pdf

OUT = Path("build/bakeoff")


def _try(label: str, fn: Callable[[], Path], doc: RenderDoc) -> None:
    try:
        pdf = fn()
    except Exception as exc:  # noqa: BLE001 - operator script reports, never crashes
        print(f"{label}: UN-RUNNABLE ({exc})")
        return
    violations = run_l7(doc, parse_pdf(pdf))
    status = "PASS" if not violations else f"FAIL ({len(violations)})"
    print(f"{label}: {pdf}  L7 {status}")
    for violation in violations:
        print(f"    - {violation}")


def main() -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", default="backend")
    parser.add_argument("--template", type=Path, default=None,
                        help="path to the user's .tex; omit to skip arm (a)")
    args = parser.parse_args()

    profile = load_profile("config/master_profile.yaml")
    doc = build_render_doc(profile, args.variant)
    OUT.mkdir(parents=True, exist_ok=True)

    if args.template is None:
        print("arm (a) LaTeX: SKIPPED (no --template supplied)")
    else:
        from src.render.latex import render_latex
        _try("arm (a) LaTeX",
             lambda: render_latex(doc, args.template, OUT / "latex.pdf"), doc)

    from src.render.rendercv import render_rendercv
    _try("arm (b) RenderCV",
         lambda: render_rendercv(doc, OUT / "rendercv.pdf"), doc)

    print("\nOpen both PDFs and judge visual acceptability. That call is the user's.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
