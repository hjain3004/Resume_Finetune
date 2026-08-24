# M8P-3 — Constrained S3 Alignment and Static G1 Design

**Date:** 2026-08-23

**Status:** Approved for planning and implementation by the user's 2026-08-23
instruction to proceed to the next task and provide the execution prompt

**Phase:** 3 (M8 Tailoring)

**Predecessors:** M8P-1 (`f6cb99e`), M8P-2/M8P-2R (`779d05d`,
`931db85`), and the duplicate S0-reference repair (`bd5f8ab`)

**Next milestone after completion:** M8P-4 (G2 anchored critic and bounded
revision loop). M8P-3 does not begin M8P-4.

## 1. Goal

M8P-3 turns a validated M8P-2 structural selection into a deterministic,
traceable resume draft without allowing the model to choose new projects,
bullets, claims, metrics, or structure.

It adds:

1. a privacy-minimised S3 alignment request;
2. a strict S3 edit contract;
3. deterministic hydration from the canonical master profile and accepted S2
   structure;
4. a machine-derived change log and unified diff;
5. a single static G1 gate covering G0/L1 and the pre-render portions of
   L2-L6; and
6. one-job, offline-safe preparation/invocation CLI commands.

The milestone ends at an accepted `s3_bundle.json`. It does not produce a PDF,
run the G2 critic, ask the user to review a resume, mutate SQLite, or mark M8 or
Phase 3 complete.

## 2. Fixed boundaries

- One job at a time; no batch mode or 3/30-resume pilot.
- The authoritative inputs are the complete validated M8P-1/M8P-2 artifact
  chain plus the current master profile and read-only production DB row.
- Jobs 229 and 279 remain prohibited.
- Preparation re-runs `src.db.prepare_tailoring_request()` and revalidates the
  complete upstream chain. Persisted JSON is never trusted merely because it
  exists.
- The model receives no raw JD, identity/contact data, education, evidence,
  defense, interview risk, metric ledger, known gaps, Company Bank data, file
  paths, or tools.
- The S3 call uses `invoke_text_model()`: tools disabled, session persistence
  disabled, no shell, one attempt, no retries.
- Every raw stdout is written through the existing I11 trace mechanism.
- Tests never call a real model, network, or `pdflatex`.
- No new dependency is permitted.
- No SQLite write, status transition, note, flag, score, or application row is
  permitted.
- A failed invocation, parse, semantic validation, hydration, or G1 run never
  overwrites an earlier accepted `s3_bundle.json`.
- No Company Bank lookup or external research is added; S0 remains `jd_only`.

## 3. Why S3 emits edits, not a resume

S2 is the only stage allowed to choose the base variant, project set, and
bullet order. Allowing S3 to emit a document would silently give it those
decisions again and would make structure and provenance model-owned.

S3 therefore emits only two bounded edit lists:

- edits to the text of already selected bullet ids; and
- additions of exact, covered S1 requirement terms to existing skill
  categories.

Everything else is derived deterministically. Unmentioned bullets remain at
their canonical default phrasing. Original skills remain present. The accepted
draft's structure comes only from S2 and the current master profile.

This design deliberately retires `src/tailor/wrapper.py`'s legacy
`hydrate_tailor_draft()` and `derive_change_list()` implementations rather
than reviving them. Those dict-based helpers silently skip unknown ids, infer
ownership from naming conventions, and fabricate vague change reasons. They
remain non-production legacy until removed in a later cleanup milestone.

## 4. Canonical S3 alignment view

M8P-3 adds `AlignmentView`, produced from the current `MasterProfile` and a
validated `S2Response`. It contains only:

- `base_variant`;
- selected project ids in S2 order;
- immutable experience ids in canonical order;
- selected bullets in exact S2 order, each with:
  - `bullet_id`, `owner_id`, and `owner_kind`;
  - the canonical default source text (the same `medium -> short` fallback used
    by `src.render.mapping.build_render_doc()`);
  - parsed plain text and emphasis spans;
  - `keywords_hit` and `claim_type`;
- the canonical skills mapping;
- `do_not_claim`; and
- a deterministic SHA-256 fingerprint of the canonical JSON projection.

It omits identity/contact data, education, ownership-boundary prose, evidence,
defense, interview risk, metrics, known gaps, unused bullets, and unused
projects. Blocked bullets cannot enter because S2 and the profile loader both
reject them; the alignment builder checks again and fails closed.

The model receives the marked canonical source text because emphasis is part
of the source contract. Deterministic parsing converts it to plain text for
lint and edit-distance calculations.

## 5. S3 request contract

`S3Request` is a frozen dataclass containing:

- `job_id`, `company`, and `title`;
- validated `S1Response`, `S0Response`, and `S2Response`;
- the `AlignmentView`;
- constant `context_mode = "jd_only"`.

The serializer emits strict JSON. The parser rejects missing/unexpected fields,
wrong types, booleans where integers are expected, empty required strings or
lists, duplicate ids/terms, and any invalid nested upstream object.

Preparation proves all identities agree, the current DB row is still eligible,
the DB-recommended base variant still matches the canonical M8P-2 catalog, the
persisted M8P-2 catalog equals a newly derived profile catalog, and the accepted
S2 response still passes `validate_s2_response()`.

## 6. S3 response contract

The model returns exactly:

```json
{
  "bullet_edits": [
    {
      "bullet_id": "exact selected bullet id",
      "after": "complete replacement text with valid **emphasis** markers",
      "motivating_terms": ["exact covered S1 must_have term"],
      "rule": "terminology_mirroring"
    }
  ],
  "skill_additions": [
    {
      "category": "exact existing skill category",
      "term": "exact covered S1 must_have term",
      "motivating_term": "same exact term"
    }
  ]
}
```

`rule` is exactly `terminology_mirroring` or `xyz_tightening`. Unchanged
bullets are omitted. Empty edit/addition lists are valid when the canonical
selection already satisfies G1.

Structural parsing rejects:

- markdown fences, repaired JSON, missing/unexpected fields, and wrong types;
- empty strings;
- duplicate bullet edits;
- duplicate normalized motivating terms within an edit;
- duplicate skill additions by normalized `(category, term)`;
- more than eight bullet edits, matching `TAILORING_SPEC.md` section 3; and
- an edit whose `after` text is byte-identical to its canonical source.

## 7. Deterministic S3 semantic validation

Publication requires every edit to satisfy all of the following:

1. `bullet_id` is selected by S2 and resolves in the current alignment view.
2. Every `motivating_term` is an exact, case-sensitive S1 `must_have` term.
3. Every motivating term is `covered` by S2 and the edited bullet id appears
   in that term's coverage entry.
4. `after` parses through `parse_emphasis()`; malformed, empty, whitespace-
   ambiguous, or otherwise invalid emphasis is rejected.
5. The first normalized word is identical before and after. The canonical
   action verb is therefore preserved rather than guessed from an English
   word list.
6. The normalized numeric-token multiset is identical before and after. An
   edit cannot add, remove, alter, or duplicate any metric. This implements
   the user's explicit requirement that all metrics remain present.
7. `after` contains no newline and its plain-text character count does not
   exceed the canonical plain-text count.
8. Every newly introduced non-function token appears in at least one cited
   motivating term. The fixed function-word allowlist contains only closed-
   class grammar words needed to restructure a sentence; it contains no
   technologies, domain nouns, quantities, or adjectives.
9. `xyz_tightening` may reorder or remove existing tokens but receives no
   wider vocabulary allowance than terminology mirroring.
10. The edit is included in the global token edit-distance calculation.

Every skill addition must satisfy:

1. the category exists in the canonical skills mapping;
2. `term == motivating_term` exactly;
3. the term is an exact S1 `must_have` term with `covered` S2 status;
4. at least one coverage bullet remains selected;
5. the term does not collide with `do_not_claim` under case-folded,
   whitespace-collapsed comparison; and
6. the term is not already present anywhere in canonical skills or earlier
   additions under normalized comparison.

S3 cannot remove a canonical skill or invent a category. Hydration preserves
every original category and skill in original order, appending accepted terms
to the requested existing categories in response order.

## 8. Deterministic hydration and derived review artifacts

`hydrate_s3()` combines the validated S2 structure, alignment view, and S3
response into a frozen `TailoredDraft`:

- selected projects exactly in S2 order;
- immutable experiences exactly in canonical order;
- bullets exactly in S2 `bullet_order`, with canonical ownership and either
  canonical or validated edited text;
- canonical skills plus validated additions; and
- the alignment fingerprint.

The model does not provide `before`, owner ids, project ids, experience ids,
section names, ordering, emphasis offsets, change-log prose, or a diff.

Code derives:

- one `ChangeEntry` for every bullet edit and skill addition;
- the motivating JD quote by looking up each exact S1 requirement term;
- token edit distance over all selected bullet plain text plus the skills
  mapping, excluding S2-only reorders;
- a stable unified diff between canonical and tailored plain-text projections;
  and
- a stable static G1 report.

This removes six opportunities for the model's explanation to disagree with
the actual artifact.

## 9. Static G1 contract

M8P-3 adds `run_static_g1()` and one typed `G1Report`. It executes all static
checks before the future G2 call:

- **G0/L1 traceability and structure:** every bullet has a canonical id and
  owner; project ids, experience ids, bullet order/count, skill-category set,
  and fixed section skeleton match S2/profile expectations exactly.
- **L2 lexicon:** no banned word or phrase appears in bullet or skills text.
  Terms come from `config/banned_words.txt`, parsed deterministically with
  blank/comment lines ignored and boundary-aware phrase matching.
- **L3 keyword bounds:** each `covered` S1 must-have appears in at least one of
  its mapped bullets and in skills; `gap` terms are explicitly exempt and stay
  gaps. No must-have occurs more than four times document-wide. The first five
  covered must-haves in S1 order must occur two or three times.
- **L4 static bullet shape:** every edited bullet has valid emphasis, no
  newline, the same leading canonical action verb, an identical numeric-token
  multiset, and no plain-text length growth. These are the claims M8P-3 can
  prove without rendering.
- **L5 edit budget:** token edit distance over bullet wording and skills is at
  most `0.15`; pure S2 structure selection/reordering is excluded.
- **L6 do-not-claim/blocked claims:** no `do_not_claim` phrase appears in any
  bullet or skill and no blocked bullet is present.

The current `src/tailor/lint.py` contains partial helpers, but it has no G1
aggregator and no draft-level banned-lexicon check. M8P-3 may retain compatible
public helpers, but production publication must use the new typed aggregate;
passing a hand-selected subset of old helpers is not sufficient.

### 9.1 Honest boundary for rendered line counts

`TAILORING_METHODOLOGY.md` describes L4 as “every modified bullet <= 2 lines
rendered.” A pre-render pure function cannot know line wraps, and a character
threshold is not a rendered measurement. M8P-3 therefore does not fabricate a
line-count oracle. Its no-growth rule ensures S3 cannot make a canonical bullet
longer while preserving every metric. Exact wrap/page/overlap checks remain a
post-render responsibility of the already selected LaTeX arm and L7.

The `G1Report` records `render_line_check = "pending"`. M8P-3 may report
`static_pass`, never final deliverability. M8/PDF completion later requires the
real render plus L7; no M8P-3 document may claim otherwise.

## 10. Invocation, tracing, and accepted artifact

`S3OutcomeKind` has:

- `invocation_failure`;
- `parse_failure`;
- `semantic_failure`;
- `hydration_failure`;
- `g1_failure`; and
- `valid`.

`run_s3_invocation()` builds the protected prompt, calls
`invoke_text_model()`, writes an I11 trace whenever raw output exists, strictly
parses and validates the response, hydrates the draft, derives review
artifacts, and runs static G1. A G1 violation produces `g1_failure`; the future
G2 critic is not invoked. `S3Outcome` follows the existing stage-outcome pattern
and carries `trace_path`; a `g1_failure` also carries the complete typed
`G1Report` so deterministic diagnostics are not collapsed into one error string.

Only `valid` may publish the single authoritative `s3_bundle.json`, containing:

- schema version and job identity;
- alignment fingerprint;
- parsed S3 response;
- hydrated draft;
- derived change log;
- unified diff;
- wording-delta numerator, denominator, and ratio; and
- full static G1 report, including `render_line_check = "pending"`.

One JSON bundle is used so a crash cannot publish a new draft with an old lint
report or change log. It is written with `write_json_atomic()`. Raw model output
exists only in immutable traces.

## 11. CLI

The CLI is `python -m scripts.tailor_s3`:

1. `prepare --job-id ID --db PATH --profile PATH --s1-request PATH --s1 PATH
   --s0-request PATH --s0 PATH --s2-request PATH --s2 PATH --output DIR`
   revalidates the complete chain and atomically writes `s3_request.json`.
2. `invoke --request PATH --banned-words PATH --output DIR
   [--prompt-template PATH] [--trace-dir PATH] [--timeout SECONDS] [--dry-run]`
   validates/builds the prompt. `--dry-run` makes no model call, trace, or
   accepted artifact. A real valid run writes `s3_bundle.json` atomically.

The default prompt is `docs/prompts/tailoring_s3.md`; the default banned list
is `config/banned_words.txt`; the default trace root is `data/traces`.

## 12. Explicit non-goals

M8P-3 does not implement or start:

- G2 critic, revisions, or the two-round loop;
- G3 human packet, taste capture, gap aggregation, or approval;
- application directories, archival indexes, or golden-set promotion;
- final LaTeX source, PDF rendering, L7 execution, or delivered resumes;
- database mutation or `TAILORED` status;
- Company Bank Track C or company-aware S0/S2/G3 integration;
- live model calls or any 3/30-resume pilot;
- batch tailoring;
- M9F-1, M9D-1, discovery, ingestion, scoring, or eligibility work;
- dependency additions; or
- cleanup of unrelated legacy helpers.

## 13. Acceptance criteria

- Every new parser/validator/hydrator/lint is pure and covered by focused tests.
- S3 cannot change S2 structure, cite an uncovered term, edit an unmapped
  bullet, add/change/drop a metric, introduce uncited content vocabulary,
  remove canonical skills, add a do-not-claim term, or exceed eight bullet
  edits.
- The unified diff and change log are derived from the actual hydrated draft,
  not accepted from model output.
- G0/L1 and static L2-L6 each have pass and violation tests; an aggregate test
  proves any violation blocks publication.
- The 15% calculation exposes numerator, denominator, and ratio and has exact
  under/equal/over-boundary tests.
- Strict prompt shape, invocation outcomes, I11 tracing, true dry-run, failed-
  rerun preservation, and atomic bundle publication are tested with mocks.
- Real `config/master_profile.yaml` plus offline synthetic upstream artifacts
  can prepare and round-trip an `s3_request.json`; no pilot job is invoked.
- Focused tests and the full suite pass; `git diff --check` is clean; the
  production DB checksum remains
  `a9966f4afa4771b61e5b1838c9930e4c64062dc9d85d6fbb49cef17447843ae1`.
- Documentation marks only M8P-3's offline/static portion complete. Phase 3,
  M8, G2/G3, final rendering, and both human pilots remain incomplete.
