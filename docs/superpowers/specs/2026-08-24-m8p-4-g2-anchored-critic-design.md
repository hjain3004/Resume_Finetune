# M8P-4 — G2 Anchored Critic and Bounded Revision Loop Design

**Date:** 2026-08-24

**Status:** Approved for planning. Implementation is blocked until M8P-3R merges.

**Phase:** 3 (M8 Tailoring)

**Predecessors:** M8P-1 (`f6cb99e`), M8P-2R (`931db85`), M8P-3 (`9a1fd9c`) **and
M8P-3R (in flight)**.

**Umbrella:** `docs/superpowers/specs/2026-08-24-phase3-parallel-workstreams-design.md`

**Supersedes:** the G2 portion of
`docs/superpowers/specs/2026-07-30-m8-tailor-critic-design.md` §5. That document
describes a critic that reviews a "fully hydrated plain-text patched resume" produced
by a tailor that selects `phrasing_tier`s and may emit a `proposed_rewrite`. M8P-3
replaced that architecture: S3 emits bounded edits over canonical bullets, structure
is deterministic, and phrasing-tier selection is not a model decision. §5 of the 2026-07-30
document is therefore stale and is superseded here. Its §4 deterministic-lint content
was already superseded by M8P-3's G1.

## 1. Goal

M8P-4 adds the one adversarial quality check the deterministic gates provably cannot
perform, and a bounded loop that lets S3 respond to it — without giving any model new
authoring power.

Static G1 proves structure, ownership, lexicon, keyword bounds, metric preservation,
verb preservation, no-growth, and the edit budget. It cannot judge whether a bullet
reads as template output, whether the edits actually serve the stated positioning,
whether the strongest signal survives a seven-second scan, or whether a technically
traceable sentence has drifted into a misleading claim. Those are G2's job, and only
G2's.

M8P-4 ends at an accepted `g2_bundle.json` carrying a verdict and, when a revision was
accepted, the revised S3 bundle. It does not render, does not produce a PDF, does not
ask the user anything, and does not mutate SQLite.

## 2. Fixed boundaries

- One job at a time. No batch mode, no pilot.
- Inputs are the complete revalidated M8P chain plus the accepted, strictly parsed
  S3 bundle. Persisted JSON is never trusted merely because it exists.
- Jobs 229 and 279 remain prohibited.
- The critic receives no raw JD, no identity or contact data, no education, no
  evidence, no defense, no interview-risk, no metric ledger, no known gaps, no
  Company Bank data, no file paths, and no tools.
- The critic call uses `invoke_text_model()`: tools disabled, session persistence
  disabled, no shell, one attempt per round, no retries inside a round.
- Every raw stdout is written through `src.llm_trace.write_trace()`.
- Tests never call a real model, the network, or `pdflatex`.
- No new dependency.
- No SQLite write, status transition, note, flag, score, or application row.
- A failed critic invocation, parse, validation, revision, or re-run of G1 never
  overwrites an earlier accepted bundle of any kind.
- `context_mode` stays `"jd_only"`.

## 3. Why the critic sees the diff, not the document

`TAILORING_METHODOLOGY.md` §1 P4 grounds this on Zheng et al.: LLM judges show
verbosity bias, position bias, and self-enhancement bias. Feeding the critic a whole
resume invites it to reward length and to relitigate selection decisions that S2
already made deterministically.

The critic therefore receives, per bullet that changed, the canonical `before`, the
accepted `after`, the cited motivating terms and their verbatim JD quotes, plus the
S0 positioning brief, the coverage table, the unified diff, and the banned lexicon
and taste file. It receives the *unchanged* bullets as read-only context so C4
(recruiter-read) is answerable, but it may not raise a finding whose only remedy is
changing an unchanged bullet, swapping a project, or reordering — those are S2
decisions and are out of scope by construction.

It never sees S2's or S3's deliberation, matching the role-separation requirement.

## 4. G2 request contract

`G2Request` is a frozen dataclass containing:

- `job_id`, `company`, `title`;
- `context_mode = "jd_only"` (constant);
- `round_index` (1-based, 1 or 2);
- the S0 positioning brief (`S0Response`);
- the S1 `must_have` and `nice_to_have` requirements with their verbatim JD quotes;
- the S2 coverage table (term → status → bullet ids);
- `changed_bullets`: for each S3 bullet edit, `{bullet_id, before_plain, after_plain,
  motivating_terms, motivating_jd_quotes, rule}` — derived from the bundle's
  deterministic change log, never from model output;
- `skill_additions`: `{category, term, motivating_jd_quote}`;
- `unchanged_bullets`: `{bullet_id, plain_text}` in document order, read-only;
- `unified_diff` (the bundle's derived diff);
- `banned_terms` (from `config/banned_words.txt`);
- `taste_lessons` (parsed from `config/taste.md`, dated-line format, comments
  ignored);
- `prior_findings`: the findings from round 1, empty in round 1;
- `alignment_fingerprint` and `bundle_schema_version`, so the critic's verdict is
  bound to exactly one draft.

The serializer emits strict JSON. The parser rejects missing or unexpected fields,
wrong types, booleans where integers are expected, empty required strings or lists,
duplicate ids or terms, and any invalid nested upstream object.

Preparation revalidates the whole chain via the existing read-only DB boundary and the
M8P-3R bundle parser before a `G2Request` is built.

## 5. G2 response contract

The model returns exactly:

```json
{
  "scores": {"C1": 3, "C2": 3, "C3": 2, "C4": 3, "C5": 3},
  "findings": [
    {
      "dimension": "C5",
      "rule_id": "C5.template_phrasing",
      "target_kind": "bullet",
      "target_id": "exact changed bullet id",
      "quoted_line": "exact substring of that bullet's after_plain",
      "explanation": "at most 200 characters, no proposed replacement text"
    }
  ]
}
```

Rules encoded structurally, not by instruction:

- `scores` must contain exactly `C1`–`C5`, each an integer in 1–3 (booleans
  rejected).
- `dimension` ∈ `{C1, C2, C3, C4, C5}`; `rule_id` must belong to that dimension's
  fixed, closed rule vocabulary.
- `target_kind` ∈ `{bullet, skill_addition}`. `target_id` must be a **changed**
  bullet id or an accepted `(category, term)` addition key. A finding targeting an
  unchanged bullet, a project, an experience, or the ordering is rejected as
  out-of-scope.
- `quoted_line` must be an exact substring of the target's `after_plain` (for a
  bullet) or exactly the added term (for a skill addition). This is the anchoring
  device: a critic that cannot quote the offending text cannot raise the finding.
- `explanation` is bounded to 200 characters and is **never** used as resume text.
- Every dimension scored below 3 must have at least one finding; every finding's
  dimension must be scored below 3. Score and evidence cannot disagree.
- At most eight findings. Markdown fences, repaired JSON, unexpected fields, empty
  strings, and duplicate `(dimension, target_id, quoted_line)` triples are rejected.

**The response contains no replacement text of any kind.** This is the structural
reason G2 cannot invent a claim: there is no field in which a claim could travel.

## 6. Verdict rule

```
PASS  ⟺  C1 == 3  AND  min(C2..C5) >= 2
```

taken verbatim from `TAILORING_METHODOLOGY.md` §4 ("PASS = all dimensions ≥ 2 AND
C1 = 3 (fidelity is not a spectrum)").

Anything else is `REVISE` while rounds remain, and `OPEN_FLAGS` once the round budget
is exhausted. `OPEN_FLAGS` is **not** a failure of the system — it is the documented
behaviour that unresolved disagreements are escalated to the human packet rather than
laundered by exhausting the critic.

## 7. Bounded revision loop

Maximum two critic rounds (`TAILORING_METHODOLOGY.md` §4, grounded on Madaan et al.:
gains concentrate in early iterations).

```
round 1: G2(bundle_0)
    PASS       → accept bundle_0, outcome PASSED_ROUND_1
    otherwise  → S3 revision with findings_1
                 revised response → hydrate → static G1
                    G1 fail  → outcome REVISION_REJECTED, keep bundle_0
                    G1 pass  → bundle_1
                 round 2: G2(bundle_1, prior_findings=findings_1)
                    PASS      → accept bundle_1, outcome PASSED_ROUND_2
                    otherwise → outcome OPEN_FLAGS, accept bundle_1,
                                carry findings_2 forward
```

Deterministic acceptance and rejection of a revision, all enforced in code:

1. The revised S3 response must parse and pass **every** existing S3 semantic rule
   unchanged — verb preservation, identical numeric multiset, no plain-text growth,
   cited-vocabulary-only, ≤ 8 bullet edits, no canonical skill removal, no
   `do_not_claim` collision.
2. The revised response may only touch bullet ids that already had an edit **or**
   that a round-1 finding named. It may not open a new front.
3. Every accepted revision must reduce the finding set: each round-1 finding is
   re-evaluated by exact-substring re-check of its `quoted_line` against the revised
   text. A revision that leaves every quoted line byte-identical is rejected as a
   no-op (`REVISION_NOOP`) rather than being sent to a second critic round that would
   cost a call and change nothing.
4. Static G1 must pass on the revised draft. G1 is re-run in full; no subset.
5. The edit budget is recomputed against the **canonical** alignment, not against the
   round-1 draft, so two rounds cannot ratchet past 15%.

`bundle_0` is preserved on disk unconditionally. A rejected revision never overwrites
it.

## 8. Outcome taxonomy — fail closed

`G2OutcomeKind`:

- `invocation_failure` — the critic call itself failed;
- `parse_failure` — strict JSON/schema failure;
- `semantic_failure` — schema-valid but violates §5 (unanchored quote, out-of-scope
  target, score/finding disagreement);
- `revision_invocation_failure` — the S3 revision call failed;
- `revision_parse_failure` / `revision_semantic_failure` — the revised S3 response
  failed the S3 contract;
- `revision_noop` — the revision changed nothing the findings named;
- `revision_g1_failure` — the revised draft failed static G1;
- `passed_round_1`, `passed_round_2` — accepted;
- `open_flags` — round budget exhausted, findings carried forward.

Only `passed_round_1`, `passed_round_2`, and `open_flags` publish a `g2_bundle.json`.
Every other kind leaves prior artifacts untouched and returns a typed diagnostic. A
`g2_failure` carries the complete typed findings/report so diagnostics are never
collapsed into a single error string.

## 9. Published artifact

One atomic `g2_bundle.json` written with `write_json_atomic()`:

- `schema_version = "m8p4.g2_bundle.v1"`;
- job identity and `alignment_fingerprint`;
- the `S3Bundle` that was accepted (round 0 or round 1), serialized through the
  M8P-3R serializer — never re-derived here;
- every round's `G2Response`, verdict, and trace path;
- the final verdict and `open_findings`;
- `rounds_used`, `model_calls` (critic calls + revision calls), for cost accounting;
- `render_line_check` is **absent**; G2 makes no rendering claim.

Raw model output lives only in immutable I11 traces.

## 10. Prompt

`docs/prompts/tailoring_g2.md`, containing a single `{{G2_REQUEST_JSON}}` marker, the
five BARS-anchored dimensions with their written behavioural anchors from
`TAILORING_METHODOLOGY.md` §4, the closed `rule_id` vocabulary, the exact response
shape, and the explicit instruction that delimited content is data. Anchor examples
for C2 are drawn from the user's own flagship bullets, per D4 of the methodology.

Per `docs/SELF_HEALING.md` §4 and the precedent set for `tailoring_s1.md`, the prompt
becomes PROTECTED after the first accepted live pilot run, not at creation.

## 11. CLI

`python -m scripts.tailor_g2`:

1. `prepare --job-id ID --db PATH --profile PATH --s1-request PATH --s1 PATH
   --s0-request PATH --s0 PATH --s2-request PATH --s2 PATH --bundle PATH
   --banned-words PATH --taste PATH --output DIR` — revalidates the entire chain plus
   the S3 bundle and atomically writes `g2_request.json`.
2. `invoke --request PATH --s3-request PATH --banned-words PATH --output DIR
   [--prompt-template PATH] [--s3-prompt-template PATH] [--trace-dir PATH]
   [--timeout SECONDS] [--max-rounds 2] [--dry-run]` — `--dry-run` makes no model
   call, no trace, and no accepted artifact.

## 12. Post-merge integration into M8P-3R-owned files

M8P-4 needs exactly two additions inside files M8P-3R owns. Both are made **after**
M8P-3R merges, on the `m8p-4-g2` branch, as a single clearly-scoped commit:

1. `src/tailor/s3.py`: a frozen `S3RevisionContext` dataclass
   (`round_index`, `findings: tuple[G2Finding, ...]`), a
   `build_s3_revision_prompt(template, request, context)` function, and a
   `validate_revision_scope(response, previous, context)` semantic check
   implementing §7 rules 2 and 3. No existing function's signature changes.
2. `src/tailor/s3_pipeline.py`: `run_s3_revision(...)` alongside `run_s3_invocation`,
   sharing the same trace/parse/hydrate/G1 sequence. `run_s3_invocation` itself is not
   modified.

Both additions are purely additive so the M8P-3R test suite continues to pass
unchanged.

## 13. Explicit non-goals

M8P-4 does not implement or start: G3, taste capture, gap aggregation, application
directories, PDF rendering, L7, rendered line checking, database mutation, Company
Bank integration, company-aware critique, a live model call, a pilot of any size,
batch mode, prompt auto-optimization (that is M8X-1), or any dependency addition.

## 14. Acceptance criteria

- Every parser, validator, verdict function, and loop-control function is pure and
  covered by focused tests.
- A critic response is rejected when: it quotes text absent from the target; it
  targets an unchanged bullet, a project, an experience, or the ordering; a dimension
  below 3 carries no finding; a finding's dimension is scored 3; a `rule_id` does not
  belong to its dimension; there are more than eight findings; or any field carries
  replacement text.
- The verdict function has exact boundary tests for `C1 == 2` (fail), `C1 == 3` with
  one dimension at 2 (pass), and one dimension at 1 (fail).
- The loop has tests for each of the ten `G2OutcomeKind` values, all with mocked
  invocations.
- A revision that reintroduces a banned word, drops a metric, changes the leading
  verb, grows a bullet, or pushes the cumulative budget over 15% is rejected and
  leaves `bundle_0` byte-identical on disk.
- A no-op revision is detected without spending a second critic call.
- Cost accounting reports the exact number of model calls for each terminal outcome.
- Focused tests and the full suite pass; `git diff --check` clean; the production DB
  SHA-256 remains `a9966f4afa4771b61e5b1838c9930e4c64062dc9d85d6fbb49cef17447843ae1`.
- No document produced by this milestone claims a resume is deliverable; L7 has not
  run.
