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
import dataclasses
import json
import sys
from pathlib import Path

from src.tailor2_eval.baseline_registry import empty_registry, load_baseline_registry
from src.tailor2_eval.blind import blind_package_to_dict
from src.tailor2_eval.codex_selection import load_private_selection_manifest
from src.tailor2_eval.metrics import compute_aggregate_summary
from src.tailor2_eval.orchestrator import LiveModeNotAuthorizedError, run_evaluation_plan
from src.tailor2_eval.pairing import answer_key_entry_to_dict, build_blind_pairs_batch
from src.tailor2_eval.plan import PlanValidationError, load_plan, validate_plan_against_repo, validate_plan_file
from src.tailor2_eval.release_gate import evaluate_release_gate
from src.tailor2_eval.reports import generate_all_reports
from src.tailor2_eval.schemas import human_review_from_dict, target_result_from_dict


def _fail(label: str, msg: str) -> int:
    print(f"[{label}] {msg}", file=sys.stderr)
    return 1


def cmd_validate_plan(args: argparse.Namespace) -> int:
    try:
        targets = load_private_selection_manifest(Path(args.targets_manifest)) if args.targets_manifest else None
        if targets is None:
            plan = validate_plan_file(Path(args.plan))
        else:
            plan = load_plan(Path(args.plan))
            validate_plan_against_repo(plan, targets=targets)
    except (PlanValidationError, FileNotFoundError, KeyError, ValueError) as exc:
        return _fail("INVALID_PLAN", str(exc))
    print(f"Plan {plan.plan_id!r} is valid: {len(plan.target_ids)} target(s), resume_policy={plan.resume_policy!r}.")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    try:
        targets = load_private_selection_manifest(Path(args.targets_manifest)) if args.targets_manifest else None
        if targets is None:
            plan = validate_plan_file(Path(args.plan))
        else:
            plan = load_plan(Path(args.plan))
            validate_plan_against_repo(plan, targets=targets)
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
            provider=args.provider,
            targets=targets,
        )
    except LiveModeNotAuthorizedError as exc:
        return _fail("LIVE_NOT_AUTHORIZED", str(exc))
    except NotImplementedError as exc:
        return _fail("LIVE_NOT_IMPLEMENTED", str(exc))

    cost_text = summary.cost_status if summary.cost_status != "reported" else f"${summary.total_cost_usd:.4f}"
    print(f"mode={mode} targets_run={len(summary.results)} calls={summary.provider_calls_made} cost={cost_text}")
    if summary.stopped_on_budget:
        print("WARNING: run stopped early -- max_calls/max_cost_usd budget reached.", file=sys.stderr)
    return 0


def _read_resume_text(path_str: str, base_dir: Path) -> str:
    """Best-effort read of a résumé text artifact for a blind package. A
    missing file (common while wiring this up before real artifacts exist)
    never crashes the CLI -- it yields a visibly-placeholder string instead
    of silently fabricating résumé content."""
    if not path_str:
        return ""
    candidate_path = Path(path_str)
    if not candidate_path.is_absolute():
        candidate_path = base_dir / candidate_path
    if candidate_path.exists():
        return candidate_path.read_text(encoding="utf-8")
    return f"[resume text not found on disk: {path_str}]"


def cmd_build_blind_pairs(args: argparse.Namespace) -> int:
    """Pairs each candidate TargetResult against a genuinely distinct
    baseline resolved from --baseline-registry (never against itself -- see
    src.tailor2_eval.pairing for the self-pair guard). Writes reviewer-safe
    BlindPackages to `out_dir`, the private AnswerKeyEntry for each pair
    under `out_dir/answer_key/` (never merged into the reviewer file), and a
    `pairing_report.json` recording every included and excluded target."""
    results_dir = Path(args.results_dir)
    out_dir = Path(args.out_dir) if args.out_dir else results_dir / "blind_pairs"
    answer_key_dir = out_dir / "answer_key"
    out_dir.mkdir(parents=True, exist_ok=True)
    answer_key_dir.mkdir(parents=True, exist_ok=True)

    result_files = sorted(results_dir.glob("*/result.json"))
    if not result_files:
        return _fail("NO_RESULTS", f"no result.json files found under {results_dir}")

    candidate_results = [target_result_from_dict(json.loads(p.read_text(encoding="utf-8"))) for p in result_files]

    if args.baseline_registry:
        registry = load_baseline_registry(Path(args.baseline_registry))
    else:
        registry = empty_registry()
        print(
            "WARNING: no --baseline-registry given; every target will be excluded "
            "(no_baseline_available) rather than paired against itself.",
            file=sys.stderr,
        )

    resume_text_by_candidate_run_id = {
        r.run_id: _read_resume_text(
            r.artifact_paths.get("resume_text") or r.artifact_paths.get("resume_text_fallback") or "", results_dir
        )
        for r in candidate_results
    }
    baseline_paths = {entry.resume_text_path for kinds in registry.entries.values() for entry in kinds.values()}
    resume_text_baseline_lookup = {p: _read_resume_text(p, Path(".")) for p in baseline_paths}

    report = build_blind_pairs_batch(
        candidate_results,
        registry,
        seed=args.seed,
        resume_text_by_candidate_run_id=resume_text_by_candidate_run_id,
        resume_text_baseline_lookup=resume_text_baseline_lookup,
        diagnostic_mode=args.diagnostic_identical,
    )

    for pair, package, answer_key in report.included:
        (out_dir / f"{pair.comparison_id}.json").write_text(
            json.dumps(blind_package_to_dict(package), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (answer_key_dir / f"{pair.comparison_id}.json").write_text(
            json.dumps(answer_key_entry_to_dict(answer_key), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    exclusions = [dataclasses.asdict(e) for e in report.excluded]
    (out_dir / "pairing_report.json").write_text(
        json.dumps(
            {"included": [p.comparison_id for p, _, _ in report.included], "excluded": exclusions},
            indent=2, sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )

    print(f"Wrote {len(report.included)} comparison pair(s) to {out_dir} (answer keys under {answer_key_dir})")
    if report.excluded:
        print(f"Excluded {len(report.excluded)} target(s); see {out_dir / 'pairing_report.json'}", file=sys.stderr)
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
    validate_plan_cmd.add_argument("--targets-manifest", default=None)
    validate_plan_cmd.set_defaults(func=cmd_validate_plan)

    run = sub.add_parser("run")
    run.add_argument("plan")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--recorded", metavar="FIXTURE_DIR", default=None)
    run.add_argument("--live", action="store_true")
    run.add_argument("--provider", default=None, help="Explicit live provider; codex_subscription uses ChatGPT-managed Codex auth.")
    run.add_argument("--targets-manifest", default=None, help="Private Codex selection manifest for live pilot targets.")
    run.set_defaults(func=cmd_run)

    build_pairs = sub.add_parser("build-blind-pairs")
    build_pairs.add_argument("results_dir")
    build_pairs.add_argument("--out-dir", default=None)
    build_pairs.add_argument(
        "--baseline-registry", default=None,
        help="Path to a baseline_registry.json mapping target_id -> {old_pipeline|manual|accepted_historical|alternate_config: {...}}. "
        "Without this, every target is excluded (never self-paired).",
    )
    build_pairs.add_argument("--seed", type=int, default=0, help="Deterministic A/B ordering seed.")
    build_pairs.add_argument(
        "--diagnostic-identical", action="store_true",
        help="Bypass the self-pair guard for controlled same-system diagnostic comparisons. Never the default.",
    )
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
