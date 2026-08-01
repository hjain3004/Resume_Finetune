"""Record render fixtures once, offline. Committed output; never run in tests."""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

FIXTURE_DIR = Path("tests/fixtures/render")


def compile_tex(tex_path: Path, out_pdf: Path) -> None:
    if shutil.which("pdflatex") is None:
        sys.exit("pdflatex not found; cannot record a LaTeX fixture")
    workdir = out_pdf.parent
    workdir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["pdflatex", "-interaction=nonstopmode", "-output-directory", str(workdir),
         str(tex_path)],
        check=True,
        capture_output=True,
    )
    produced = workdir / (tex_path.stem + ".pdf")
    produced.replace(out_pdf)
    for junk in workdir.glob(tex_path.stem + ".*"):
        if junk.suffix in {".aux", ".log", ".out"}:
            junk.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tex", type=Path, help="source .tex to compile")
    parser.add_argument("name", help="fixture name, e.g. good_single_column")
    args = parser.parse_args()
    out = FIXTURE_DIR / f"{args.name}.pdf"
    compile_tex(args.tex, out)
    print(f"recorded {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
