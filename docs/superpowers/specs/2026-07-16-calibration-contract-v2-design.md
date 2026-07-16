# Calibration Contract v2 Design

**Status:** Approved by the user on 2026-07-16.

## 1. Purpose

The first Phase 2 worksheet, `data/calibration/2026-07-12.user.md`, records decisions made
from digest metadata only. The scorer, however, reads JD text. Comparing those two judgments
as though they answer the same question produced false calibration disagreements: an
attractive company/title could receive `APPLY` before the user saw a citizenship restriction,
specialty mismatch, or experience requirement that correctly lowered the model score.

Calibration Contract v2 separates two legitimate human judgments:

- `interest_call`: the metadata-only decision to pursue or open a posting;
- `fit_call`: the final decision after reading the complete JD.

Only `fit_call` is ground truth for calibrating the model's 7+ shortlist boundary.
`interest_call` remains useful for measuring what the JD changed, but it is never treated as
a model error.

## 2. Milestone boundary

This is one self-contained milestone named **Calibration Contract v2**. It includes:

- a versioned two-stage calibration artifact contract;
- deterministic selection of a configurable number of canonical job groups, default 12;
- metadata-only interest worksheet generation;
- validated reveal of a full-JD fit worksheet;
- strict provenance, completeness, grouping, and locked-label validation;
- corrected comparison semantics in `scripts/calibration_report.py`;
- preservation and explicit legacy handling of the existing worksheet;
- offline tests and documentation.

It does not include:

- changing `docs/scoring_prompt.md`, `config/profile_summary.md`, scoring aggregation, or
  model invocation behavior;
- changing the score threshold from 7;
- changing job status, scores, the live database, or the database schema;
- actually completing a new human calibration round;
- re-anchoring provisional stress bands from evidence that does not exist yet;
- implementing M8, M9D-1, discovery work, tailoring, or a new dependency.

The milestone produces the trustworthy mechanism needed for subsequent human calibration;
it does not claim that Phase 2 calibration is complete.

## 3. Human decision semantics

### 3.1 `interest_call`

The user sees only canonical ID/grouping, company, title, locations, flags, and JD quality.
The worksheet contains no JD text and no model score.

- `APPLY`: based on metadata, the user expects they would submit an application.
- `MAYBE`: the posting is worth opening and reviewing, but metadata is insufficient for a
  submission decision.
- `SKIP`: the user would not pursue it based on metadata.

### 3.2 `fit_call`

After all interest calls are complete and locked, the user reads the complete JD. The model
score remains hidden.

- `APPLY`: after reading the complete JD, the user would submit an application.
- `MAYBE`: after reading the complete JD, the posting remains worth human review.
- `SKIP`: after reading the complete JD, the user would not submit an application.

For a 7+ shortlist, both `APPLY` and `MAYBE` are positive. `SKIP` is negative. Calls are
accepted case-insensitively while editing and normalized to uppercase.

## 4. Blind staged workflow

One fresh calibration round follows this order:

1. Export current eligibility-passed `RESOLVED` jobs using the existing exporter.
2. Start a v2 round from that exported JSON. Deterministically take the first N canonical
   objects in source order; N defaults to 12 and is configurable with `--limit`.
3. Write an immutable round scoring batch containing exactly those objects and a metadata-
   only `*.interest.md` worksheet tied to it by SHA-256.
4. The user completes every `interest_call` without opening the source batch or seeing JDs.
5. Reveal the fit worksheet. The command validates the interest artifact and hashes, reads
   complete representative JDs from SQLite in read-only mode, and writes `*.fit.md`.
6. The user completes every `fit_call` without seeing model scores.
7. Score the immutable round batch with the existing scorer.
8. Run the v2 calibration report against the completed fit worksheet and scored JSON.
9. Optionally run the existing score import as a separate normal pipeline operation; it is
   not part of this milestone or required to produce the calibration report.

The default of 12 aligns with the scorer's existing chunk size of six. Two complete rounds
produce 24 JD-informed labels, exceeding the Phase 2 minimum without allowing tiny batches
to satisfy the evidence gate.

## 5. Artifact layout and provenance

For round name `2026-07-16`, `scripts/calibration_packet.py start` writes these files under
`data/calibration/` unless `--out-dir` is supplied:

- `2026-07-16.batch.json`: the immutable N-object scoring batch;
- `2026-07-16.interest.md`: metadata-only worksheet.

`reveal` writes:

- `2026-07-16.fit.md`: full-JD worksheet.

Commands refuse to overwrite any existing output. Writes use a same-directory temporary
file followed by atomic replacement; failures remove temporary files and leave no partial
official artifact.

Both Markdown artifacts begin with YAML front matter. Interest metadata is:

```yaml
---
contract_version: 2
stage: interest
round: "2026-07-16"
batch_path: "data/calibration/2026-07-16.batch.json"
batch_sha256: "<64 lowercase hex characters>"
canonical_job_count: 12
created_at: "<UTC ISO-8601 timestamp>"
---
```

Fit metadata additionally contains:

```yaml
interest_path: "data/calibration/2026-07-16.interest.md"
interest_sha256: "<hash of the completed interest worksheet>"
```

Paths are recorded relative to the repository root when possible. The parser resolves a
relative path against the repository root, not the current shell directory.

## 6. Worksheet body contract

### 6.1 Interest worksheet

The editable table has exactly these columns:

```markdown
| id | row_ids | company | title | locations | flags | jd_quality | interest_call | notes |
```

The generator safely escapes table cell pipes and normalizes newlines. `id` is the canonical
representative ID. `row_ids` is the complete sorted comma-separated group. Locations and
flags are rendered deterministically. Only `interest_call` and `notes` are editable.

The interest parser validates:

- front matter and exact contract/stage values;
- a readable batch whose current SHA-256 matches `batch_sha256`;
- exactly `canonical_job_count` data rows;
- each batch canonical ID exactly once, in batch order;
- exact `row_ids`, company, title, locations, flags, and JD-quality values;
- no missing, duplicate, extra, or invented canonical group;
- every call is `APPLY`, `MAYBE`, or `SKIP` before reveal.

### 6.2 Fit worksheet

The summary table has exactly these columns:

```markdown
| id | row_ids | company | title | locations | flags | jd_quality | interest_call | fit_call | notes |
```

The copied `interest_call` is locked by both the recorded interest-file hash and exact
comparison with the parsed source interest worksheet. Only `fit_call` and fit notes are
editable.

After the table, each canonical job appears once in batch order:

```markdown
## Job 123 — Example Company — Software Engineer

JD SHA-256: `<hash of the complete representative JD>`

<!-- CALIBRATION_JD_START id=123 -->
<complete literal JD text>
<!-- CALIBRATION_JD_END id=123 -->
```

The marker IDs and hashes prevent section swapping or silent truncation. Literal JD text is
not parsed as instructions. Marker strings occurring in source JD text are escaped for the
worksheet and restored only for hashing/validation.

The fit parser validates every interest invariant plus:

- the current interest file matches `interest_sha256`;
- copied interest calls have not changed;
- each JD section exists exactly once and matches its canonical ID;
- its hash matches the rendered complete JD;
- every fit call is valid and complete before comparison.

## 7. Complete JD retrieval

The scoring batch intentionally truncates `jd_text` at approximately 6,000 characters. It
therefore cannot be the source for a full-JD human judgment.

`reveal` opens the configured SQLite database read-only and requests the canonical
representative IDs through a query helper in `src/db.py`. It verifies every requested ID
exists and that its company and title still match the round batch. It uses that row's complete
`jd_text` and rejects missing/empty text. Group members remain represented by the one
canonical object exactly as they are for scoring.

Read-only mode must not initialize/migrate SQLite, create a missing database, start a run,
change job state, or update timestamps. A before/after database-byte/hash test proves reveal
does not write.

## 8. Legacy worksheet handling

`data/calibration/2026-07-12.user.md` remains byte-for-byte unchanged. Its table's `your
call` values are parsed as legacy metadata-only `interest_call` values.

The parser returns an explicit contract/stage distinction rather than inventing fit labels.
The v2 report refuses to compare a legacy interest-only worksheet against model scores and
prints a clear instruction to create a fresh v2 round. Existing legacy parsing use cases and
tests remain supported.

The historical 30 labels do not count toward the JD-informed Phase 2 minimum. They remain
valid evidence about metadata appeal and about why the old comparison contract was flawed.

## 9. Calibration report contract

The preferred reproducible command is:

```bash
python -m scripts.calibration_report \
  data/calibration/2026-07-16.fit.md \
  --scored-file data/calibration/2026-07-16.scored.json
```

The report loads the fit worksheet's round batch, verifies the scored file covers every
canonical `id` and exact `row_ids` once, and then classifies at the threshold loaded from
`config/filters.yaml`. `--threshold` remains an analysis override for compatibility. The
milestone does not change the configured value.

Comparison truth table:

| `fit_call` | score | classification |
|---|---:|---|
| APPLY or MAYBE | >= threshold | agreement |
| APPLY or MAYBE | < threshold | false negative / disagreement |
| SKIP | < threshold | agreement |
| SKIP | >= threshold | false positive / disagreement |

The report prints:

- paths, contract version, round, batch hash, and threshold;
- canonical, interest-labeled, fit-labeled, scored, and unscored counts;
- fit-label counts;
- agreement count/rate, false-negative count, and false-positive count;
- each disagreement with ID, company, title, calls, score, and notes;
- a complete 3x3 `interest_call -> fit_call` transition matrix;
- every decision changed after reading the JD.

Interest-to-fit changes are diagnostic, never scoring disagreements. Missing scores are
listed and make the round incomplete. Valid disagreements do not cause a nonzero exit;
malformed/provenance-inconsistent/incomplete human artifacts do.

The current `--db` lookup remains available for legacy operational compatibility, but v2
comparison prefers `--scored-file`. It still requires a v2 fit worksheet; it cannot convert
legacy interest labels into fit ground truth.

## 10. Phase 2 evidence gate

The corrected Phase 2 evidence gate is:

- at least 20 fresh eligibility-passed canonical jobs with complete JD-informed fit labels;
- at least two complete v2 rounds;
- at least 10 canonical jobs in each round;
- two consecutive complete rounds with zero threshold-crossing disagreements;
- provisional stress bands re-anchored from actual fit-label evidence;
- the shortlist threshold locked only after evidence supports it.

This implementation milestone does not satisfy that gate by itself, re-anchor bands, or lock
a new threshold. It only makes subsequent evidence trustworthy.

## 11. Errors and observability

- Invalid YAML/front matter, unsupported versions/stages, invalid calls, missing files,
  hash mismatches, metadata drift, changed interest calls, duplicate/missing/extra IDs,
  grouping mismatches, incomplete JDs, and scored coverage errors name the artifact and job
  involved and exit nonzero.
- Start/reveal log only paths and counts, never JD bodies.
- Existing outputs cause a refusal, not silent replacement.
- User notes never affect parsing except normal safe table decoding.
- The tool makes no model calls and performs no network access.

## 12. Testing and acceptance

Automated tests use temporary files and temporary SQLite databases only. Coverage includes:

- deterministic default-12 selection and configurable limits;
- stable batch ordering and hashes;
- interest packets contain no JD text or score fields;
- Markdown escaping round trips metadata and notes;
- reveal refuses incomplete interest calls;
- fit packets contain complete, untruncated JDs and correct hashes;
- source batch, interest hash, locked call, metadata, grouping, JD section, and score coverage
  mismatches are rejected;
- calls normalize case-insensitively;
- APPLY and MAYBE are positive, SKIP negative;
- transition matrices and changed-decision lists are exact;
- missing scores prevent completion without deleting human evidence;
- legacy worksheet parsing remains supported but comparison is refused;
- no-overwrite and atomic failure behavior;
- read-only JD retrieval leaves database bytes unchanged;
- existing export, scoring, importing, audit, and full-suite tests stay green.

The milestone is complete when code, tests, and authoritative docs implement this contract,
the full suite passes, and the work is committed. It stops before creating a real v2 round,
running scoring, importing scores, changing protected scoring inputs, changing the threshold,
or starting M8/M9D.
