# Tailor2 quality_core — design notes

First production-hardening slice of the LLM-first tailoring lane. This is an
implementation, layered on top of the existing 4-stage lane
(draft -> audit -> conditional repair -> re-audit -> render), not a rewrite.
Every existing strength (strict JSON/dataclass contracts, evidence-ID and
numeric-token grounding, resumable artifacts, multi-provider support,
one-page enforcement) is preserved unchanged; nothing in `src/tailor2/`
was deleted or restructured beyond what was needed to add the pieces below.

## Why: what was wrong before

The auditor only ever saw isolated bullet text plus that one bullet's cited
evidence. It could not see the résumé's title line, the Skills section, or
any other bullet, so it structurally could not catch a title mismatch, an
unsupported Skills entry, or the same abstract term repeated three times
across different bullets — even in principle. Separately, `validate_audit_response`'s
"score 1 on any dimension forces verdict=REJECT, and any rejection forces
the whole run to fail" rule treated a fabricated number and a repetitive
adjective identically: both produced a hard rejection. That made the lane
brittle in the wrong direction — quality nits and factual fabrications were
handled the same way.

## Severity model (`src/tailor2/severity.py`)

Four tiers, matching the task's explicit policy:

| Tier | Meaning | Outcome |
|---|---|---|
| `FATAL_INTEGRITY` | Fabricated/unresolved evidence, invented numbers, prohibited claims, unverifiable provenance, an invalid structured response, or an unrenderable document | `REJECTED_FATAL` |
| `AUTO_CORRECTABLE` | Deterministically fixable without model judgment (title/employer mismatch, unsupported Skills entry) | Corrected silently, run continues |
| `REPAIRABLE_QUALITY` | Writing-quality or positioning defect | Bounded targeted repair, not rejection |
| `ADVISORY_GAP` | Profile has no evidence for a JD capability | Disclosed, never invented, never blocks |

`DIMENSION_SEVERITY` in `severity.py` maps every rubric dimension (the
original 9 bullet-level ones plus the 8 new whole-résumé ones) to a tier,
with the reasoning for each placement documented inline in that file. The
two dimensions classified fatal are `factual_fidelity` and `metric_fidelity`
— the only two whose failure mode is "the claim isn't true," which cannot be
fixed without inventing evidence. Everything else is a wording, positioning,
or clarity problem a repair pass can address without touching the facts.

**Important separation of concerns**: `validators.validate_audit_response`
is unchanged — it still enforces that a dimension scoring 1 implies
`verdict=REJECT` on that evaluation, and that any rejection implies
`overall_verdict=REPAIR_REQUIRED`. That is a schema-consistency rule about
the audit *response*, not a policy about what the *lane* does next. The new
`validators.classify_evaluation_severity` / `classify_whole_resume_severity`
functions are a separate layer that decides, given a rejected evaluation,
whether it's fatal or repairable. This split means the severity policy can
be reasoned about and tested independently of response-schema validity.

## Five run states (`severity.RunStatus`)

`ACCEPTED`, `ACCEPTED_WITH_WARNINGS`, `REPAIR_REQUIRED` (transient, not
normally a terminal state a completed run returns), `NEEDS_HUMAN_REVIEW`,
`REJECTED_FATAL`. Final resolution logic (`run_tailor2_lane`, "FINAL STATUS
RESOLUTION"):

- Any page-fill variance (PDF compiled but isn't exactly one page) or an
  unresolved `REPAIRABLE_QUALITY` finding (repair budget exhausted, or a
  whole-résumé-only finding with no single-bullet target) -> `NEEDS_HUMAN_REVIEW`.
- Any `AUTO_CORRECTABLE` fix was applied, or an `ADVISORY_GAP` was found ->
  `ACCEPTED_WITH_WARNINGS`.
- Otherwise -> `ACCEPTED`.
- A `FATAL_INTEGRITY` finding anywhere short-circuits immediately to
  `REJECTED_FATAL`, before render is even attempted.

**Deliberate exception**: the same-model draft/audit disclosure (below) is
recorded in `manifest.warnings` but does **not** by itself downgrade
`ACCEPTED` to `ACCEPTED_WITH_WARNINGS`. It is a structural disclosure about
review independence, not a quality signal about the résumé itself, and
almost every existing call site (and the two "immutable" frozen-fixture
regression tests) uses a single invoker for both stages — downgrading their
status on that basis alone would have been a purely cosmetic, unjustified
backward-compatibility break.

## 1. Drafter/auditor model separation

`run_tailor2_lane(..., invoker, auditor_invoker=None, repair_invoker=None,
re_audit_invoker=None, acknowledge_same_model=False)`. `invoker` keeps its
exact pre-existing meaning and position (the drafter). When
`auditor_invoker` is omitted, the drafter invoker is reused for
audit/repair/re-audit — the historical single-invoker behavior, so every
existing call site is unaffected. `repair_invoker`/`re_audit_invoker`
default to `auditor_invoker` (the audit-side identity performs repair and
re-audit unless told otherwise).

When drafter and auditor share the same provider+model, a warning is
logged and recorded in `manifest.warnings`
(`same_model_draft_and_audit: true` in the manifest either way).
`acknowledge_same_model=True` suppresses only the console log line for a
deliberate same-model run; the manifest disclosure is never suppressed.
CLI flags: `--auditor-provider`, `--auditor-model`, `--acknowledge-same-model`,
`--repair-budget` (`scripts/tailor2.py`) — named to parallel the existing
`--provider`/`--model` flags rather than invent a new naming scheme.

All four identities (drafter/auditor/repair/re_audit) are persisted in the
manifest as `{stage}_provider`/`{stage}_model` pairs, plus the legacy
`provider`/`model` fields (still the drafter's identity, for readers that
only know the old schema).

## 2. Whole-résumé audit projection (`src/tailor2/audit_projection.py`)

`build_resume_projection()` assembles: company/title/variant, section
order, every entry's employer/project name and *resolved* displayed title
(post title-policy correction) or tech line, every selected bullet in
final order with its cited evidence, the complete Skills section (each
term flagged `supported`/`unsupported` against this run's selected
evidence — not the whole profile), atomic-requirement-to-evidence coverage
(and which requirements have no supporting bullet), the omission ledger,
and all four model identities. Never the drafter's chain-of-thought.

This is embedded (as JSON) into the audit and re-audit prompts alongside
the existing per-bullet content — `build_audit_prompt`/`build_repair_prompt`/
`build_re_audit_prompt` all gained a new **optional trailing** `projection`
parameter so direct unit-test callers (`tests/tailor2/test_prompts.py`)
that construct their own bullet lists are completely unaffected; only
`lane.py`'s real call sites pass it.

## 3. Eight new whole-résumé audit dimensions

`metric_interpretability`, `interview_defensibility`,
`whole_resume_positioning`, `skills_evidence_integrity`,
`title_identity_fidelity`, `mechanism_outcome_balance`,
`cross_bullet_repetition`, `misleading_implication` — scored once per audit
call against the complete projection, in a `whole_resume` block alongside
the existing per-bullet `evaluations` array. Schema in `models.py`
(`WholeResumeEvaluation`, `REQUIRED_WHOLE_RESUME_DIMENSIONS`); rubric text
in `prompts._WHOLE_RESUME_RUBRIC`.

`whole_resume` is an **optional** field on `AuditResponse` — a legacy fixture
or hand-built test response that omits it is treated as "whole-résumé
auditing was not evaluated for this response" (a recorded warning), not a
parse error. New runs always request and receive it.

No naïve word bans were added anywhere. "Agentic," "orchestration," and
similar terms are legitimate when precise and sparing; the
`cross_bullet_repetition` dimension is a judgment call the LLM auditor
makes by reading the whole résumé, not a regex over a banned-word list.

## 4. Deterministic checks (`title_policy.py`, `validators.py`)

- **Title/employer fidelity** (`title_policy.resolve_displayed_title`):
  `src/profile.py` is out of this task's scope and the profile's own
  `title` field is documented as immutable, so this does not add a schema
  field to the profile. Instead `DraftResponse.entry_title_overrides`
  (entry_id -> proposed title) gives the drafter a narrow, auditable
  channel — exactly the "seed the target title in the summary line only"
  pattern the profile's own `known_gaps` note anticipates. A proposal that
  isn't the canonical title or a listed `APPROVED_TITLE_VARIANTS` entry is
  silently corrected back to canonical (`AUTO_CORRECTABLE`); the correction
  is recorded in `manifest.auto_corrections`, never a rejection.
- **Skills-evidence integrity** (`validators.check_skills_evidence_integrity`
  / `apply_deterministic_auto_corrections`): every Skills term is checked
  against this run's *selected* evidence (not the whole profile); an
  unsupported term is removed from what actually renders, and the removal
  is disclosed. This is a real, previously-absent behavior change:
  `render.py` used to dump the entire `profile.skills` list minus
  `do_not_claim` regardless of what the tailored bullets actually
  demonstrated.
- **Approximation-marker fidelity** (`~40%` vs `40%`): unchanged from the
  pre-existing `validators.extract_numeric_tokens` /
  `_normalize_num_token` machinery, which already treats a bare and
  `~`-prefixed token as equivalent against the evidence's own hedging.
- **No independent-review claim without manifest support**: the
  same-model disclosure (above) is the enforcement point — an audit can
  never be silently presented as cross-model when it wasn't.
- **Repaired output preserves evidence IDs/numerics**: unchanged
  pre-existing `validate_repair_response` behavior, still exercised on
  every repair.
- **Re-audit evaluates the complete repaired résumé**: the re-audit prompt
  always receives the full post-splice `ResumeProjection` (every bullet,
  not just the repaired fragment) via the same whole-résumé mechanism as
  the first audit; see `lane._audit_repair_cycle`.

## 5. Targeted repair

`build_repair_prompt` gained optional `projection` (full-résumé context)
and `protected_facts` (a bounded list of "bullet X's evidence/numerics are
out of scope for this call") parameters. The rejected bullets remain the
only editable targets; the prompt explicitly instructs the model to
preserve every supported achievement while improving clarity, not resolve
a critique by deleting the accomplishment.

After repair: the spliced draft is re-validated deterministically
(`validate_draft_response`), a fresh `ResumeProjection` is built from it,
and the re-audit call evaluates that complete projection. If re-audit
still finds a `REPAIRABLE_QUALITY` issue and the repair budget (default 1
cycle, `--repair-budget`) is exhausted, the run resolves to
`NEEDS_HUMAN_REVIEW` with the last-known-good draft rendered and
delivered — never a silent pass and never a fatal rejection for a
writing-quality issue.

## 6. Rendering and page fill

Page count != 1 no longer aborts the run. The PDF is compiled and
delivered; if it isn't exactly one page, the run resolves to
`NEEDS_HUMAN_REVIEW` with the artifact preserved rather than discarded.

## 7. Artifact preservation

Every stage's JSON (`draft.json`, `audit.json`, `repair.json`,
`draft_repaired.json`, `re_audit.json`) is still written incrementally as
it's produced, unchanged from before. `run_manifest.json` is written to
`out_dir` directly (not a `rejected/` subdirectory) for every non-fatal
outcome, including `NEEDS_HUMAN_REVIEW` and `ACCEPTED_WITH_WARNINGS` — only
`REJECTED_FATAL` writes to `out_dir/rejected/`, since that is the one
outcome that doesn't produce a résumé anyone should submit.

## Known limitations (deliberately deferred)

This is a first slice, not the complete system the task sketches. Deferred,
each because it is a substantial independent feature rather than a small
addition to what's here:

1. **Rendered multi-candidate selection.** The bounded offline selection layer
   now requests a small configurable candidate set, applies deterministic
   integrity filtering, persists component rankings, and performs a whole-
   résumé safe selection pass. It deliberately does not replace the existing
   draft contract's authority over sections, entries, or ordering; rendered
   line-fill optimization remains deferred.
2. **Active page-fill expansion/compression.** The renderer no longer
   *fails* on page-count variance (see above), but it does not yet add
   unused high-value evidence to fill remaining space or algorithmically
   compress wording/spacing to reclaim a slight overflow. Today: compile,
   measure, and if not exactly one page, preserve the artifact and mark
   `NEEDS_HUMAN_REVIEW`.
3. **Automated repair for whole-résumé-only findings with no single-bullet
   target.** When `cross_bullet_repetition` or `misleading_implication`
   rejects the whole résumé but no individual bullet was flagged, there is
   no principled way (in this slice) to choose which bullets to rewrite.
   Rather than guess, the run goes straight to `NEEDS_HUMAN_REVIEW` with
   the best available artifact. See
   `_audit_repair_cycle`'s `whole_resume_repairable and not repairable_bullet_ids`
   branch.
4. **`APPROVED_TITLE_VARIANTS` is a small, hand-maintained table** (two
   entries, matching the two profile experience entries that currently
   exist) rather than a general policy mechanism. Adding a new approved
   variant means editing `title_policy.py` directly.
