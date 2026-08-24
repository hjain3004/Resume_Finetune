# M8P-6 — G3 Human Review Packet and Feedback Contract Design

**Date:** 2026-08-24

**Status:** Approved for planning. Task group A (the feedback contract) may be
implemented in parallel with M8P-3R; task group B (the packet builder) requires
M8P-4 and M8P-5 merged.

**Phase:** 3 (M8 Tailoring)

**Predecessors:** M8P-3R, M8P-4 (G2 verdict type), M8P-5 (render result type).

**Umbrella:** `docs/superpowers/specs/2026-08-24-phase3-parallel-workstreams-design.md`

## 1. Goal

Give the user everything needed to judge one tailored resume in about two minutes,
and capture that judgement in a machine-readable, append-only, versioned form that can
later become taste rules, lint rules, a golden set, and — much later — evaluation data
for M8X-1.

`TAILORING_METHODOLOGY.md` §4 sets the target: "The packet: coverage table, change log,
critic verdict, open flags, gap report, rendered PDF. Target review time ≤ 2 minutes."
M8P-6 implements exactly that, plus the feedback side the methodology only sketches.

## 2. No web UI

Nothing in the approved documentation authorises a web interface, a server, or a
frontend dependency. The packet is a **Markdown file the user reads** next to the
already-rendered PDF, and the feedback form is a **YAML file the user edits**. PyYAML
is already an approved dependency. This keeps the whole loop inside the file-contract
pattern the rest of the system uses and adds nothing to install.

## 3. Fixed boundaries

- No model call. G3 is entirely deterministic code. The critic already ran in G2.
- No SQLite write.
- No new dependency.
- No network. Tests never call a model, the network, or `pdflatex`.
- `src/tailor/s3.py`, `g1.py`, `s3_pipeline.py`, `scripts/tailor_s3.py`, and existing
  M8P-3/M8P-4/M8P-5 tests are read-only.
- M8P-6 never writes `config/taste.md`, `config/banned_words.txt`, or any prompt. It
  *derives* candidate lessons; a human or M8P-7 applies them.
- Feedback is stored under `data/feedback/`, which is already gitignored via `data/`.
  The packet is written into the gitignored application directory beside the PDF.

## 4. The packet

Written into the application directory created by M8P-5:

```
applications/{company-slug}-{role-slug}/
├── review.md              # what the user reads
├── packet.json            # schema_version "m8p6.review_packet.v1"
└── feedback_form.yaml     # what the user fills in
```

`review.md` sections, in fixed order — designed so the first screen answers "should I
send this?" and everything below is evidence:

1. **Header** — company, title, job id, base variant, date, PDF path, and one
   status line: `G1 static_pass · G2 pass (round 1) · L7 pass · line check pass`.
2. **Warnings and open flags** — G2 open findings, S1 `suspected_injection`, S2 `gap`
   terms, and any advisory L7 finding. Empty section is printed as
   `None.` rather than omitted, so its absence is never ambiguous.
3. **What this job asks for** — the S1 `must_have` terms with their verbatim JD
   quotes, capped at the first twelve by S1 order with an explicit
   `(+N more)` line rather than a silent truncation.
4. **What was selected and why** — base variant, project ids with S2's one-line
   reasons, and the S0 positioning brief verbatim.
5. **What changed** — one row per change-log entry: location, before, after, the
   motivating JD quote, and the rule. This is the section the methodology says the
   user reviews *instead of* the whole resume.
6. **Coverage** — each `must_have` term → `covered` (with bullet ids) or `GAP`.
7. **Gate detail** — the edit-budget numerator/denominator/ratio, the G1 violation
   list (empty on pass), every G2 round's five scores and findings, the L7 violation
   list, and the per-modified-bullet rendered line counts.
8. **Full canonical-vs-tailored diff** — the bundle's derived unified diff, last,
   because it is the least skimmable artifact.

`packet.json` carries the same content as typed data so nothing downstream has to
parse Markdown.

**Everything in the packet is derived from already-validated artifacts.** The builder
performs no independent judgement, invents no prose, and never re-summarises with a
model — a "concise S1 summary" here means a deterministic projection of validated
fields, not a generated abstract.

## 5. The feedback contract

`feedback_form.yaml` is emitted pre-populated with the assessment keys and empty
values, plus the bullet ids that changed so bullet-level comments have somewhere
structured to go:

```yaml
# Fill in every non-optional field. Leave a comment empty rather than inventing one.
schema_version: "m8p6.feedback_record.v1"
job_id: 225
alignment_fingerprint: "…"
reviewed_at: ""                    # YYYY-MM-DD

accept: ""                         # accept | reject
would_submit: ""                   # yes | no | not_as_is
needs_another_revision: ""         # yes | no

company_alignment: ""              # 1 | 2 | 3   (3 = clearly speaks to this company/product)
visual_quality: ""                 # 1 | 2 | 3   (3 = would hand this to a recruiter as-is)

bullet_feedback:                   # one entry per changed bullet; comment may be empty
  - bullet_id: "b_xxx"
    verdict: ""                    # keep | reword | revert
    comment: ""

missing_skills: []                 # terms the resume should have surfaced and did not
overemphasized_skills: []          # terms given more weight than the evidence supports
unsupported_claims: []             # {bullet_id, quoted_text, why} — anything misleading

free_form: ""
```

Parsed into a frozen `FeedbackRecord`. Validation is strict and fails closed:

- `accept`, `would_submit`, `needs_another_revision` are closed enums; empty is an
  error, not a default.
- `company_alignment` and `visual_quality` are integers 1–3 (booleans rejected).
- `reviewed_at` must be a valid `YYYY-MM-DD` date.
- `bullet_feedback` must cover **exactly** the changed-bullet id set — no extra ids,
  no missing ids, no duplicates. A reviewer cannot silently skip a bullet.
- Every `unsupported_claims` entry must name a real bullet id and quote an exact
  substring of that bullet's rendered plain text. This is the same anchoring device
  G2 uses, applied to the human: an unsupported-claim report that cannot be located
  is a form error, so the record stays actionable.
- `missing_skills` and `overemphasized_skills` are deduplicated, non-empty strings.
- `alignment_fingerprint` must equal the packet's, binding feedback to exactly one
  draft.

`accept == "accept"` with `would_submit == "no"` is **allowed and meaningful** — it is
the most useful signal the loop can produce ("technically fine, still wouldn't send
it") and collapsing it into one field would destroy it.

## 6. Storage, versioning, idempotency

```
data/feedback/
├── index.jsonl                                     # append-only, one line per record
└── {job_id}-{fingerprint12}-r{revision}.json       # one immutable file per record
```

- Records are **immutable**. A second assessment of the same
  `(job_id, alignment_fingerprint)` is stored as `r2`, `r3`, … and appended to the
  index. Earlier feedback is never rewritten, and the whole history is queryable.
- Writing a record whose content is byte-identical to the latest revision for that key
  is an idempotent no-op that returns `ALREADY_RECORDED` — a re-run of the CLI never
  inflates the corpus.
- `index.jsonl` lines carry `{schema_version, job_id, alignment_fingerprint, revision,
  reviewed_at, accept, would_submit, path}` — enough to compute every acceptance-gate
  statistic M8P-8 needs without opening each record.
- Every file is written with `write_json_atomic()`; the index line is appended only
  after the record file exists.
- `schema_version` is checked on read. An unknown version is a typed error, never a
  best-effort parse.

## 7. Becoming taste, lint, and golden-set input — later

M8P-6 provides one pure function and stops:

```python
def derive_taste_candidates(record: FeedbackRecord,
                            packet: ReviewPacket) -> tuple[TasteCandidate, ...]
```

Each candidate is `{date, lesson, mechanically_enforceable: bool, evidence}`. A
`reword` verdict with a comment, an `overemphasized_skills` entry, and an
`unsupported_claims` entry each yield one candidate. `mechanically_enforceable` is
`True` only when the lesson reduces to a literal term that could join
`config/banned_words.txt` — matching the methodology's `[lint]` tag rule.

**M8P-6 writes none of these anywhere.** Appending to `config/taste.md` and
`config/banned_words.txt` is a human decision, executed in M8P-7 after the pilot,
because those files are PROTECTED inputs to prompts and a change to them requires a
D2 drift re-run.

Golden-set promotion (`applications/_golden/`) and the D2 drift harness are explicitly
**not** in M8P-6. The feedback schema records what a later milestone will need
(`accept`, `would_submit`, fingerprint, revision) so promotion is a query, not a
migration.

## 8. CLI

`python -m scripts.tailor_g3`:

1. `build --bundle PATH --g2-bundle PATH --render-result PATH --s1 PATH --s0 PATH
   --s2 PATH --output DIR` — revalidates every input, writes `review.md`,
   `packet.json`, and `feedback_form.yaml` atomically. Refuses to overwrite an
   existing `packet.json` whose fingerprint differs.
2. `record --form PATH --packet PATH [--feedback-dir data/feedback]` — strictly parses
   the filled form, validates it against the packet, and stores an immutable record.
   Prints the assigned revision and path.
3. `summarize [--feedback-dir data/feedback] [--job-id ID]` — read-only. Prints the
   acceptance statistics M8P-8's gate needs: counts by `accept`, by `would_submit`,
   mean `company_alignment`, mean `visual_quality`, and the number of records
   requiring another revision. Writes nothing.

## 9. Outcomes

`G3OutcomeKind`: `input_mismatch`, `already_built`, `conflict`, `built`;
`FeedbackOutcomeKind`: `parse_failure`, `validation_failure`, `already_recorded`,
`recorded`.

Fail-closed everywhere: a form that fails validation stores nothing, and the previous
record for that key stays byte-identical.

## 10. What can be built before M8P-4 and M8P-5 merge

| Component | Parallel-safe? | Reason |
|---|---|---|
| `FeedbackRecord`, the YAML form emitter/parser, validation, immutable storage, `index.jsonl`, idempotency, `summarize` | **Yes** | Depends only on a job id, a fingerprint string, and a changed-bullet id set — all plain values. Verified with synthetic inputs. |
| `derive_taste_candidates` | **Yes** | Pure over a `FeedbackRecord` plus a minimal packet projection. |
| `ReviewPacket` type and `review.md` builder | **No** | Needs the M8P-4 `G2Bundle`/verdict type and the M8P-5 `RenderResult` type. |
| `scripts/tailor_g3.py build` | **No** | Same. |

## 11. Explicit non-goals

M8P-6 does not implement or start: a web UI or server; writing `config/taste.md` or
`config/banned_words.txt`; the golden set or the D2 drift harness; gap aggregation into
`data/digests/gaps.md`; the `applications/by-date/` view or `INDEX.md`; database
mutation; Company Bank integration; a model call of any kind; a pilot; batch mode;
SkillOpt; or any dependency addition.

## 12. Acceptance criteria

- `review.md` renders every section in fixed order, prints `None.` for empty sections,
  caps long lists explicitly rather than truncating silently, and is byte-identical
  across two runs on identical inputs.
- `packet.json` round-trips strictly.
- The form parser rejects: an empty required enum, an out-of-range score, a boolean
  score, a malformed date, a missing or extra `bullet_feedback` id, a duplicate bullet
  id, an unsupported-claim quote that is not an exact substring of its bullet, an
  unknown `schema_version`, and a fingerprint that disagrees with the packet.
- `accept + would_submit == no` is accepted and preserved.
- Recording is immutable and append-only: a second differing assessment creates `r2`
  and leaves `r1` byte-identical; an identical re-record is `ALREADY_RECORDED` and
  appends no index line.
- `summarize` is read-only and produces the exact counts M8P-8's gate consumes.
- `derive_taste_candidates` is pure and writes nothing; a test asserts
  `config/taste.md` and `config/banned_words.txt` are untouched.
- Full suite green; `git diff --check` clean; DB SHA-256 unchanged at
  `a9966f4afa4771b61e5b1838c9930e4c64062dc9d85d6fbb49cef17447843ae1`.
