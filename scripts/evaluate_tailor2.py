"""CLI for the Tailor2 offline evaluation harness.

Safety invariant: the ONLY way any subcommand can reach a live provider is
`run PLAN.json --live`, and even then `orchestrator.run_evaluation_plan`
additionally requires a configured credential env var (see
orchestrator.LIVE_CREDENTIAL_ENV_VARS) before it does anything beyond
raising `NotImplementedError` -- live evaluation itself is out of scope for
this harness. Every other invocation (no mode flag, `--dry-run`,
`--recorded`) never constructs a live-credentialed invoker.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.tailor2_eval.blind import build_blind_pairs_from_results
from src.tailor2_eval.metrics import compute_aggregate_summary
from src.tailor2_eval.orchestrator import LiveModeNotAuthorizedError, run_evaluation_plan
from src.tailor2_eval.plan import PlanValidationError, validate_plan_file
from src.tailor2_eval.release_gate import evaluate_release_gate
from src.tailor2_eval.reports import generate_all_reports
from src.tailor2_eval.schemas import (
    ComparisonCandidate,
    ComparisonPair,
    comparison_pair_to_dict,
    human_review_from_dict,
    target_result_from_dict,
)


def _fail(label: str, msg: str) -> int:
    print(f"[{label}] {msg}", file=sys.stderr)
    return 1


def cmd_validate_plan(args: argparse.Namespace) -> int:
    try:
        plan = validate_plan_file(Path(args.plan))
    except (PlanValidationError, FileNotFoundError, KeyError, ValueError) as exc:
        return _fail("INVALID_PLAN", str(exc))
    print(f"Plan {plan.plan_id!r} is valid: {len(plan.target_ids)} target(s), resume_policy={plan.resume_policy!r}.")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    try:
        plan = validate_plan_file(Path(args.plan))
    except (PlanValidationError, FileNotFoundError, KeyError, ValueError) as exc:
        return _fail("INVALID_PLAN", str(exc))

    if args.live:
        mode = "live"
    elif args.recorded:
        mode = "recorded"
    else:
        mode = "dry_run"

    try:
        summary = run_evaluation_plan(
            plan,
            mode,
            recorded_dir=Path(args.recorded) if args.recorded else None,
            live_authorized=args.live,
        )
    except LiveModeNotAuthorizedError as exc:
        return _fail("LIVE_NOT_AUTHORIZED", str(exc))
    except NotImplementedError as exc:
        return _fail("LIVE_NOT_IMPLEMENTED", str(exc))

    print(f"mode={mode} targets_run={len(summary.results)} calls={summary.provider_calls_made} cost=${summary.total_cost_usd:.4f}")
    if summary.stopped_on_budget:
        print("WARNING: run stopped early -- max_calls/max_cost_usd budget reached.", file=sys.stderr)
    return 0


def cmd_build_blind_pairs(args: argparse.Namespace) -> int:
    results_dir = Path(args.results_dir)
    out_dir = Path(args.out_dir) if args.out_dir else results_dir / "blind_pairs"
    out_dir.mkdir(parents=True, exist_ok=True)

    result_files = sorted(results_dir.glob("*/result.json"))
    if not result_files:
        return _fail("NO_RESULTS", f"no result.json files found under {results_dir}")

    written = 0
    for path in result_files:
        data = json.loads(path.read_text(encoding="utf-8"))
        result = target_result_from_dict(data)
        resume_path = result.artifact_paths.get("resume_text")
        if not resume_path:
            continue
        pair = ComparisonPair(
            schema_version="1.0",
            comparison_id=f"cmp-{result.target_id}",
            target_id=result.target_id,
            jd_checksum=result.jd_checksum,
            profile_checksum=result.profile_checksum,
            candidate_a=ComparisonCandidate("candidate", result.run_id, result.resume_checksum or "", resume_path),
            candidate_b=ComparisonCandidate("baseline", result.run_id, result.resume_checksum or "", resume_path),
        )
        (out_dir / f"{result.target_id}.json").write_text(
            json.dumps(comparison_pair_to_dict(pair), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        written += 1

    print(f"Wrote {written} comparison pair(s) to {out_dir}")
    return 0


def cmd_aggregate(args: argparse.Namespace) -> int:
    results_dir = Path(args.results_dir)
    result_files = sorted(results_dir.glob("*/result.json"))
    if not result_files:
        return _fail("NO_RESULTS", f"no result.json files found under {results_dir}")

    results = [target_result_from_dict(json.loads(p.read_text(encoding="utf-8"))) for p in result_files]

    human_reviews = []
    reviews_dir = results_dir / "human_reviews"
    if reviews_dir.exists():
        for p in sorted(reviews_dir.glob("*.json")):
            human_reviews.append(human_review_from_dict(json.loads(p.read_text(encoding="utf-8"))))

    plan_id = args.plan_id or results_dir.name
    summary = compute_aggregate_summary(plan_id, results, human_reviews)
    gate = evaluate_release_gate(summary)

    out_dir = Path(args.out_dir) if args.out_dir else results_dir / "reports"
    paths = generate_all_reports(results, summary, gate, out_dir)

    print(f"usable_artifact_rate={summary.usable_artifact_rate:.2%} fatal_integrity_rate={summary.fatal_integrity_rate:.2%}")
    print(f"release_gate overall_pass={gate.overall_pass} (proposed thresholds, not established policy)")
    for name, path in paths.items():
        print(f"  {name}: {path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python scripts/evaluate_tailor2.py")
    sub = parser.add_subparsers(dest="command", required=True)

    validate_plan_cmd = sub.add_parser("validate-plan")
    validate_plan_cmd.add_argument("plan")
    validate_plan_cmd.set_defaults(func=cmd_validate_plan)

    run = sub.add_parser("run")
    run.add_argument("plan")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--recorded", metavar="FIXTURE_DIR", default=None)
    run.add_argument("--live", action="store_true")
    run.set_defaults(func=cmd_run)

    build_pairs = sub.add_parser("build-blind-pairs")
    build_pairs.add_argument("results_dir")
    build_pairs.add_argument("--out-dir", default=None)
    build_pairs.set_defaults(func=cmd_build_blind_pairs)

    aggregate = sub.add_parser("aggregate")
    aggregate.add_argument("results_dir")
    aggregate.add_argument("--plan-id", default=None)
    aggregate.add_argument("--out-dir", default=None)
    aggregate.set_defaults(func=cmd_aggregate)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
