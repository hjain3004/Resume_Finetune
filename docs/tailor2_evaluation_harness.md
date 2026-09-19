# Tailor2 Offline Evaluation Harness

**Status:** Implemented; the ChatGPT-managed Codex pilot lane is opt-in and bounded.
**Branch:** `feat/tailor2-luna-top10-pilot`, based on `fb101138`.
**Scope:** bounded Codex-subscription orchestration, read-only Top-10 selection, private pilot artifacts, and fake-provider tests. It does not modify `scripts/tailor2.py`, render-fill fixtures, Top-10 source manifests, or manual résumé artifacts.

## 1. Purpose

Tailor2 now has offline foundations for evidence grounding, semantic selection, multi-candidate generation, whole-résumé ranking, auditing/repair, rendering, and resumability. Before any live Top-10 run or human-preference study, the project needs orchestration, schemas, and reports that can be exercised entirely offline. This package builds that infrastructure. It **never** invokes a live model provider, mutates `data/jobs.db`, scrapes a job site, or edits Tailor2 production code.

## 2. Module map

| Module | Responsibility |
|---|---|
| `schemas.py` | Versioned dataclasses: `EvaluationPlan`, `TargetResult`, `ComparisonPair`, `HumanReviewResponse`, `AggregateSummary`, `ReleaseGateDecision`. Each has a `validate_*` function. |
| `checksums.py` | SHA-256 helpers for profile/JD/artifact identity. |
| `redact.py` | Credential redaction; also hard-rejects a plan that carries a credential-shaped field at all. |
| `plan.py` | Loads a plan and validates its checksums against the real `config/master_profile.yaml` and Top-10 JD files. |
| `targets.py` | Read-only Top-10 manifest discovery (`shortlist/tailoring_targets/targets.json`); never writes to it. |
| `orchestrator.py` | Dry-run, recorded, and bounded Codex-subscription execution with resumability and cost/call budgets. |
| `blind.py` | Deterministic, identity-hiding A/B comparison package generation. |
| `metrics.py` | Aggregate release metrics over a set of results. |
| `release_gate.py` | **Proposed** (not established) release-readiness thresholds. |
| `reports.py` | Deterministic JSON/CSV/Markdown/inventory report generation. |

## 3. Run modes and the live-call safeguard

Three modes, selected by the CLI:

- `--dry-run` (default): validates the plan and Top-10 targets, writes a `DRY_RUN_OK` placeholder per target. Never constructs `src.tailor2.invoker.Tailor2Invoker`.
- `--recorded FIXTURE_DIR`: reads one pre-baked `TargetResult` JSON per target from `FIXTURE_DIR/<target_id>.json`. Pure file I/O; also never touches `Tailor2Invoker`.
- `--live`: the CLI flag that sets `orchestrator.run_evaluation_plan(..., live_authorized=True)`. Platform-API providers remain unsupported; `--provider codex_subscription` is the separate, exact-model ChatGPT-managed lane described below.

Every test in `tests/tailor2_eval/` uses only `dry_run` and `recorded`; several assert directly that `Tailor2Invoker.invoke` was never called (via `monkeypatch.setattr` raising `AssertionError` if it is).

### 3.1 ChatGPT-managed Codex pilot lane

The only supported live pilot lane is an explicit `--live --provider codex_subscription` run using the user's authenticated Codex CLI session. It pins `gpt-5.6-luna`, starts a fresh `codex exec` process for each stage, uses `--sandbox read-only --ephemeral`, disables MCP servers for the invocation, and supplies a stage-specific strict JSON Schema. The subprocess environment excludes platform API-key and token variables; the lane never uses the platform provider adapters.

The lane enforces at most 10 targets, 120 invocations, one target at a time, and deterministic run/target deadlines. Usage is recorded as bounded counts and latency with `cost_status=not_applicable_subscription`. I11 traces may contain raw stage output and input snapshots, but remain under the ignored private pilot artifact directory and are never copied into committed/public manifests.

Pilot execution is resumable: completed result files are retained, while `INTERRUPTED`, `REJECTED_FATAL`, and `SKIPPED_BUDGET` targets can be retried only under the plan's retry policy. A canary must publish a usable artifact before the remaining targets are eligible; any fatal integrity finding or interruption stops the batch. Drafter and auditor using the same provider/model is reported explicitly and is not an independent review.

When deterministic draft validation finds a grounded canonical or selected evidence item missing, Tailor2 preserves the partial draft and makes at most two targeted `missing_evidence` requests; it never regenerates selection or the complete draft during this recovery. A returned element must pass evidence, numeric-token, prohibited-term, and full layout validation before insertion. If both attempts fail, the omission is recorded and the best safe partial is sent through the existing audit path; it becomes `NEEDS_HUMAN_REVIEW` only when a usable artifact can still be rendered, otherwise a remaining integrity or layout failure stays `REJECTED_FATAL`. Resume callers can supply the preserved draft and record reused/repeated stages in `recovery_artifacts`.

## 4. Top-10 orchestration and resumability

`orchestrator.run_evaluation_plan` iterates `plan.target_ids` in manifest order. For each target it writes `<artifact_root>/<target_id>/result.json` (via the existing `src.tailor.artifacts.write_json_atomic`, with `redact.redact_mapping` applied first) before moving to the next target. A subsequent call re-reads any existing `result.json`:

- `resume_policy="skip_completed"`: any existing result (success or failure) stands; nothing reruns.
- `resume_policy="retry_failed_only"`: only `REJECTED_FATAL` / `INTERRUPTED` / `SKIPPED_BUDGET` results are rerun.
- `resume_policy="rerun_all"`: everything reruns.

Before starting a target, the loop checks `plan.max_calls` / `plan.max_cost_usd` against calls/cost accumulated so far; once exceeded, every remaining target is written as `SKIPPED_BUDGET` and the run returns normally (no exception, no partial/corrupt state).

## 5. Blind comparison design

A `ComparisonPair` names two `ComparisonCandidate`s, each carrying an opaque `label` ("candidate", "baseline", "manual", "render_fill", ...). `blind.build_blind_package` **never copies `label` into the package** -- only `anon_id` ("candidate_1"/"candidate_2") is exposed. Ordering is `hashlib.sha256(f"{seed}:{comparison_id}")[0] % 2`, a pure function of `(seed, comparison_id)` with no stateful RNG, so the same seed always reproduces the same order for the same comparison. `validate_comparison_provenance` requires `target_id`/`jd_checksum`/`profile_checksum` to be present and shared by construction (a `ComparisonPair` has exactly one of each, not one per side, so two candidates from different JDs or profile versions cannot be paired in the first place). A comparison never requires a third "manual" candidate -- any two `ComparisonCandidate`s can be paired.

## 6. Human-review rubric

`schemas.RUBRIC_DIMENSIONS` (14 dimensions: factual trustworthiness, target-role fit, recruiter scan quality, clarity, achievement strength, metric interpretability, interview defensibility, mechanism/outcome balance, redundancy, AI-slop, Skills credibility, visual readability, page utilization, overall preference). Each dimension and the overall verdict accept `A | B | TIE | NEITHER`; there is no dimension or scoring rule that favors density, so a denser résumé is never structurally advantaged. `HumanReviewResponse` also carries `reviewer_confidence` (0.0-1.0), `free_text_concerns`, and `factual_error_flags`.

## 7. Aggregate metrics

`metrics.compute_aggregate_summary` computes, over `len(results)` (0.0 for an empty set, never a `ZeroDivisionError`): usable-artifact rate (every status except `REJECTED_FATAL`/`SKIPPED_BUDGET`), fatal-integrity rate, warning-or-human-review rate, repair frequency, average calls/cost/latency, one-page success rate, layout-warning rate, evidence-gap rate, a human-preference tally, and a factual-error-report count.

## 8. Release gate: proposed, not established policy

A repository-wide search for `G2`, `G3`, "release gate", and "pilot" found only the **unrelated legacy `src/tailor/` critic stages** (`docs/ARCHITECTURE.md`, `docs/ROADMAP.md`: G1 static critic, G2 anchored critic/revision loop, G3 review packet -- stages of the *old* `src/tailor/` pipeline, not a Tailor2-evaluation release policy). No Tailor2-evaluation release policy exists anywhere in the repo today.

`release_gate.evaluate_release_gate` therefore always sets `ReleaseGateDecision.is_established_policy = False` and its criteria (`PROPOSED_THRESHOLDS` in `release_gate.py`) are explicit proposals mirroring the task's stated "intended release direction" (zero fatal-integrity failures, a usable artifact for every Top-10 target, strong human preference over the baseline). These should be reviewed and, if adopted, recorded in `docs/DECISIONS.md` per CLAUDE.md's "docs are authoritative" rule -- this module must not be treated as that recording.

## 9. Reports

`reports.generate_all_reports` writes, deterministically (inputs sorted by `target_id` before any output): `summary.json`, `targets.csv`, `report.md`, `failure_inventory.json`, `cost_latency.json`, `human_preference.json`, `unresolved_evidence.json`, `release_gate.json`. `reports.classify_failures` buckets by `factual_failures` / `operational_failures` / `subjective_quality_concerns` / `evidence_gaps` / `layout_concerns` from `TargetResult.status`/`evidence_gaps`/`render_summary.layout_warnings` directly (no inference from free text), so a target can appear in more than one bucket and the buckets never conflate a fabricated claim with a repair-budget timeout.

## 10. Safety and privacy

- `redact.py` hard-rejects any plan containing a credential-shaped field (`plan.validate_plan_dict` raises before the plan is ever used) and redacts credential-shaped substrings from anything the orchestrator writes.
- The orchestrator never opens `data/jobs.db`, never fetches a URL, and never writes outside `plan.artifact_root` (a caller-chosen path, never a repo path by default).
- `config/master_profile.yaml` and `shortlist/tailoring_targets/targets.json` are read-only inputs; `tests/tailor2_eval/test_targets_and_orchestrator.py::test_orchestrator_never_mutates_repository_data` checksums both before and after a dry-run + recorded run.

## 11. Known limitations (deliberately deferred)

- Platform-API live evaluation remains unsupported; the bounded Codex-subscription lane is the only implemented live path and requires explicit provider selection plus exact plan identities.
- The release gate's thresholds are proposals; they have not been reviewed or ratified as repository policy.
- Platform-provider cost estimation remains outside this harness; Codex-subscription results use `cost_status=not_applicable_subscription` and retain bounded usage counts instead of inventing a dollar cost.
- `--baseline-registry` must currently be authored by hand (see §12); nothing yet auto-populates it from a real Tailor1/legacy run or a render-fill artifact.

## 12. Baseline registry and self-pair prevention (additive correction, 2026-09-18)

**Defect fixed:** the original `build-blind-pairs` (§5 as first shipped) paired each `TargetResult` against itself -- `candidate_a` and `candidate_b` both read the same `run_id`/`resume_checksum`/`resume_text_path`. Self-comparison makes any human-preference result meaningless, so this was never safe to leave executable.

**Fix:** `src/tailor2_eval/baseline_registry.py` adds `BaselineRegistry`, a read-only `target_id -> {old_pipeline | manual | accepted_historical | alternate_config: BaselineEntry}` map loaded from a JSON file (`--baseline-registry PATH`; schema: `artifact_id`, `pipeline_id`, `resume_checksum`, `resume_text_path`, `model_identities`, `provenance` per entry). `.resolve(target_id, preferred_kinds)` returns the first available kind (default order: `old_pipeline`, `accepted_historical`, `alternate_config`, `manual`) or `None` -- it never fabricates a missing artifact, and a missing `manual` entry never blocks resolution of another kind.

`src/tailor2_eval/pairing.py` is the self-pair guard:
- `check_not_self_pair(candidate, baseline, diagnostic_mode=False)` raises `SelfPairError` if the two sides share an `artifact_id`, `resume_text_path`, `resume_checksum`, or `result_run_id` -- `diagnostic_mode=True` is the **only** bypass, and it is never the default (CLI: `--diagnostic-identical`, off unless passed explicitly).
- `build_comparison_for_target` resolves a baseline through the registry, verifies `jd_checksum`/`profile_checksum` provenance, runs the self-pair check, and returns either `(ComparisonPair, BlindPackage, AnswerKeyEntry)` or a `PairExclusion` (`no_baseline_available` | `provenance_mismatch` | `self_pair_detected`) -- it never raises for a batch run, so one bad target cannot abort the rest.
- `build_comparison_between_results` is the direct two-`TargetResult` form (candidate vs. an alternate pipeline configuration, or an explicit same-system diagnostic), used when both sides already exist as results rather than one being a registry-defined baseline.
- `build_blind_pairs_batch` runs the above across every candidate result and returns a `BatchPairingReport(included, excluded)`.

**Reviewer/answer-key separation:** `ComparisonCandidate` gained additive fields (`artifact_id`, `pipeline_id`, `model_identities`, `provenance`) and `ComparisonPair` gained `purpose` -- all optional/defaulted, so every pre-existing caller and test kept working unchanged. `blind.blind_package_to_dict` was **not** changed and still only ever serializes `resume_text`/`anon_id`, so none of the new identity fields can leak into a reviewer package. Those fields are instead captured in a separate `pairing.AnswerKeyEntry`, written by the CLI to `<out_dir>/answer_key/<comparison_id>.json` -- a distinct file/directory from the reviewer package, never merged into it.

`scripts/evaluate_tailor2.py build-blind-pairs` now requires `--baseline-registry` to produce any pairs at all; omitting it prints a warning and excludes every target (`no_baseline_available`) rather than falling back to self-pairing. It also writes `<out_dir>/pairing_report.json` recording every included and excluded target with its reason.
