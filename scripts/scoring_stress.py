"""Synthetic score-band stress suite per PHASE2_KICKOFF.md M6.7 item 2.

Runs the 10 synthetic JDs in tests/fixtures/scoring_stress/cases.json through
the scorer (sub-batched via scripts.score_batch) and reports whether each
returned fit_score falls within its documented expected band. Run at
calibration start and after ANY change to docs/scoring_prompt.md or
config/profile_summary.md.

Usage: python -m scripts.scoring_stress [--out-dir DIR]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts import score_batch

CASES_PATH = Path("tests/fixtures/scoring_stress/cases.json")


def load_cases(path: Path = CASES_PATH) -> list[dict]:
    return json.loads(path.read_text())


def build_batch(cases: list[dict]) -> list[dict]:
    """Reshape stress cases into export-schema-v2 batch objects (M6.3)."""
    return [
        {
            "id": case["id"],
            "row_ids": [case["id"]],
            "company": case["company"],
            "title": case["title"],
            "locations": case["locations"],
            "flags": case["flags"],
            "jd_quality": case["jd_quality"],
            "jd_text": case["jd_text"],
        }
        for case in cases
    ]


def check_adherence(cases: list[dict], scored: list[dict]) -> list[dict]:
    scored_by_id = {entry["id"]: entry for entry in scored}
    report = []
    for case in cases:
        entry = scored_by_id.get(case["id"])
        lo, hi = case["expected_band"]
        if entry is None:
            report.append(
                {
                    "id": case["id"],
                    "category": case["category"],
                    "expected_band": case["expected_band"],
                    "actual": None,
                    "in_band": False,
                    "rationale": None,
                }
            )
            continue
        actual = entry["fit_score"]
        report.append(
            {
                "id": case["id"],
                "category": case["category"],
                "expected_band": case["expected_band"],
                "actual": actual,
                "in_band": lo <= actual <= hi,
                "rationale": entry.get("rationale"),
            }
        )
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.scoring_stress",
        description="Run the synthetic score-band stress suite and report adherence.",
    )
    parser.add_argument("--out-dir", metavar="DIR", default="data/batch", help="scratch dir for the stress batch")
    parser.add_argument("--cases", metavar="PATH", default=str(CASES_PATH), help="path to the stress cases JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    cases = load_cases(Path(args.cases))
    batch = build_batch(cases)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    batch_path = out_dir / "scoring_stress.json"
    batch_path.write_text(json.dumps(batch, indent=2))

    scored_path = score_batch.score_batch(batch_path)
    scored = json.loads(scored_path.read_text())
    report = check_adherence(cases, scored)

    passed = sum(1 for r in report if r["in_band"])
    print(f"Band adherence: {passed}/{len(report)}")
    for r in report:
        status = "PASS" if r["in_band"] else "FAIL"
        print(f"  [{status}] #{r['id']} {r['category']}: expected {r['expected_band']}, got {r['actual']}")

    return 0 if passed == len(report) else 1


if __name__ == "__main__":
    raise SystemExit(main())
