# Tailor2 Offline Release Candidate

## Integrated inputs

- Render-integrated production: `4a483645ad02098ff4ac02068fbc1feb6071e815`.
- Corrected evaluation harness: `ecb925def0b75b446b9676ca82be619d0df5ff62`.
- Evaluation plans and review assets: `b21a27a2991bc55efdb550e152fab2159b5f67e0`.
- Merge order: harness first, then plans/assets; both merges were conflict-free.

## Supported offline capabilities

- Render-fill measurement, safe expansion/compression, best-safe tracking, and fixture-backed optimizer behavior.
- Dry-run and recorded Tailor2 evaluation with resumable per-target artifacts and zero provider calls.
- Canonical baseline registry, provenance-checked pairing, self-pair rejection, blind packages, private answer keys, and deterministic JSON/CSV/Markdown reports.
- Ten-target plan validation and dry-run checks with pinned profile/JD checksums.
- Human-review assets supporting A, B, TIE, and NEITHER without provider identity in reviewer packages.

## Smoke result

The recorded OpenAI smoke used redacted fixtures in a temporary output root. Validation, dry-run, recorded replay, blind pairing, aggregation, and proposed-gate evaluation completed with one target, zero provider calls, and `$0.00` cost. The proposed gate correctly remained `False` because no human preference data was present. The reviewer package and private answer key were separate; the pair was distinct and self-pair rejection passed.

The Top-10 recorded plan validated ten targets and ten companies and completed a ten-target dry-run with zero calls and zero cost. All plan profile/JD checksums and bounded budgets validated.

## Xfails and known failures

- Retained: four historical quality-core xfails, the selection-ranking blank-space delegation xfail, automatic spacing adjustment, and normalized equivalent-draft cycle rejection.
- The blank-space behavior remains intentionally outside static selection; measured fill is a separate render-fill API.
- Automatic spacing candidates and semantic-equivalent cycle rejection are not implemented safely enough to claim support.
- Full-suite known failures remain the two renderer emphasis failures and four missing gitignored calibration-fixture failures; any sandbox-only `data` permission failures are environment issues, not code regressions.

## Proposed policy and live prerequisites

Tailor2 thresholds remain proposed, not legacy G2/G3 policy: zero fatal-integrity rate, complete usable-artifact coverage, and at least 60% candidate preference among decisive human comparisons. Live execution additionally requires a private plan with all four model placeholders resolved, explicit `--live`, provider credentials, and a user-approved budget.

The first controlled command is intentionally not executed here:

```bash
python -m scripts.evaluate_tailor2 run /path/to/resolved_openai_smoke_live.json --live
```

## Remaining boundary

This branch is an offline release-candidate foundation. It does not perform live provider evaluation, human pilots, PDF rendering as an evaluation run, database writes, Company Bank work, or later Tailor2 milestones.
