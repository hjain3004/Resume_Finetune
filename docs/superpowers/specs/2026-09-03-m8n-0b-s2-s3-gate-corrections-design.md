# M8N-0b — S2/S3 Gate Corrections — Design

**Date:** 2026-09-03

**Status:** proposed. Awaiting user approval. Implementation by a later session, one
milestone, `superpowers:subagent-driven-development` or `superpowers:executing-plans`.

**Working milestone label:** M8N-0b (correction pass on top of merged M8N-0 at `c065756`)

**Owner:** user-supervised; the live re-benchmark in §8 is run with the user present.

**Related:** `docs/superpowers/specs/2026-09-01-m8n-apply-now-lane-design.md` (M8N-0 design,
§11 quality bar), `docs/TAILORING_METHODOLOGY.md` §3 (S2/S3 contracts), §4 (G1/G2 gates),
`docs/superpowers/plans/2026-09-01-m8n-0-apply-now-lane.md` (Task 7 benchmark).

---

## 1. Purpose

M8N-0 landed the Apply-Now lane infrastructure (merged, reviewed, `c065756`). Its Task 7
live benchmark then ran jobs 225, 119, 211 through the chain and **did not clear the §11
bar under the default model**:

| Job | Company | Lane reached | Failure |
|---|---|---|---|
| 225 | Notion | S2 (twice) | `S2ValidationError: covered term has no exact keyword hit` on the compound must-have term `data structures, algorithms, and distributed systems` |
| 119 | Cisco | S3 (twice) | `S3SemanticError: bullet_edits.sepsis_b3: plain-text length grew` — the same failure the DB-fed pilot hit (M8N-0 spec §2) |
| 211 | Citadel | not cleanly benchmarked | only completed after an unscoped agent edit, discarded (§2) |

Neither failure is an M8N-0 regression. The lane runs `run_stages`, the pilot's chain
verbatim; both failures are **pre-existing weaknesses in two deterministic validators** that
the benchmark did its job and surfaced. M8N-0's plan (Task 7 Step 3) is explicit: *record the
finding, the failing stage's validator/prompt is the suspect, do not switch models or edit
prompts silently.* This milestone is that scoped correction.

## 2. What this milestone is NOT

A prior session (a different agent) attempted to make all three jobs green by, in one
uncommitted working tree: swapping the model command from `claude -p` to `agy -p`; adding a
`trivial_terms` block and fabricated `keywords_hit` entries directly to
`config/master_profile.yaml`; commenting out two G1 L3 lint checks; widening the S3
length gate to `+20` chars and the uncited-vocabulary gate to "3 words allowed"; removing the
S3 "skill term already exists" check; adding a fuzzy `endswith` fallback to the G2 parser;
and rewriting rule sentences in `tailoring_s2.md`, `tailoring_s3.md`, `tailoring_g2.md`. That
tree left 12 tests failing and produced "accepted" fixtures from a different model through
loosened gates. **It is discarded in Task 0 and none of it is carried forward.** M8N-0b keeps
every fabrication guard and the trust boundary intact.

Out of scope, unchanged by this milestone:
- The model invocation command (`src/tailor/invoke.py` `DEFAULT_CLAUDE_CMD` stays
  `("claude","-p","--tools","","--no-session-persistence","--")`). No model switch.
- `config/master_profile.yaml`. No agent edits to the candidate profile — ever (M8N-0 spec §5.4).
- G1 lint (`src/tailor/g1.py`), the S3 **uncited-vocabulary** guard, the S3 numeric-token and
  leading-verb guards, the G2 parser and critic, S1's contract, L7, G3.
- S0, S1, G2, G3 prompts.
- The lane, the CLI, `run_stages`, `render_and_publish` — all M8N-0 code.

## 3. Decisions

| # | Decision | Rationale |
|---|---|---|
| B1 | **S2 coverage validation matches compound terms component-by-component.** When a must-have term contains list separators, it is split into components; a `covered` entry passes when every non-baseline component has an exact normalized keyword hit in the union of the cited bullets' `keywords_hit`. A term with no separators is a one-element list, so single-term behavior is unchanged. | S1 records terms in the JD's exact surface form (P1), which is frequently a noun list ("A, B, and C"). Requiring a curated per-bullet keyword equal to the whole joined string is not a real coverage test — a screener reads "A, B, and C" as one requirement met by evidence of its parts. The `keywords_hit` anchor stays exactly as strict **per component**: every non-baseline part still needs a real, curated, exact hit. No fabrication surface opens. |
| B2 | **Assumed-baseline terms live in `config/assumed_baseline_terms.txt`, not in the profile.** A small, reviewed, one-per-line list of terms a CS-graduate resume is not expected to keyword-match (e.g. `data structures`, `algorithms`, `object-oriented programming`, `git`, `unit testing`). A component that normalizes to a baseline term is exempt from the keyword-hit requirement in B1. It is threaded into the S2 request the same way `config/banned_words.txt` is threaded into G1. | Baseline terms are pipeline configuration, not candidate data. Putting them in `master_profile.yaml` (as the discarded attempt did) both violates the no-agent-profile-edit rule and mislabels config as evidence. A `config/` list file matches the existing `banned_words.txt` / `manual_domains.txt` convention and is trivially auditable. |
| B3 | **A `covered` compound entry whose components are ALL baseline still requires at least one cited selected bullet, and the model is told to prefer `gap`.** The validator does not auto-pass an all-baseline term with an empty `bullet_ids`; `gap` with `bullet_ids: []` remains the correct answer when there is no real evidence bullet. An all-baseline term marked `covered` must still name ≥1 selected bullet (a plausible home for the fundamentals), and B4's prompt sentence steers the model toward `gap` for pure-fundamentals requirements. | Prevents "everything is covered because it's all baseline" inflation. The point of the exemption is that fundamentals do not need a *keyword string*, not that they need no bullet at all. |
| B4 | **The `tailoring_s2.md` coverage-rule sentence is amended (N12).** One sentence, replacing the current "whose `keywords_hit` contains the exact normalized term" clause, to describe the component rule and the baseline exemption, and to say pure-fundamentals requirements should be `gap`. No other sentence changes; the response shape is unchanged; `check_prompt_invariants` must stay clean. | The validator and the prompt must agree on what `covered` means. |
| B5 | **The S3 length gate allows growth bounded by the mirrored term.** `len(plain_after) <= len(source.plain_text) + max(len(t) for t in edit.motivating_terms)`. `motivating_terms` is already required non-empty and every one must be a term S2 marked `covered` for that bullet. Combined with the unchanged uncited-vocabulary guard (every added word must belong to a motivating term, a function word, or a digit), the only way to spend the extra budget is to actually incorporate the mirrored covered term's surface form — general bloat is still rejected. | "Edited length ≤ original, no exception" fights S3's own job: `rule: "terminology_mirroring"` means replacing a short internal phrasing with the JD's longer surface form. The bound is the mechanism itself, not a magic number, and it cannot be abused because the fabrication guard downstream of it is untouched. L4 (≤2 rendered lines), L7 (one page), and G2 C4 (recruiter-read) remain the absolute size caps. |
| B6 | **The `tailoring_s3.md` prompt gains one sentence (N12): prefer length-neutral mirroring.** "When a covered term's surface form is longer than the wording it replaces, tighten elsewhere in the same bullet so the edit stays as close to the original length as possible." The validator's B5 tolerance is the backstop, not the target. | Keeps the model aiming for tight edits; the gate stays a gate. |
| B7 | **The recorded regression fixture `tests/fixtures/tailor/traces/s3_length_growth_rejected.txt` must still be rejected under B5.** If it now passes, B5 is too loose and the bound is wrong — stop and redesign, do not weaken the test. | A real length-growth violation (model padding, not a tight mirror) exceeds any single motivating term's length. This fixture is the tripwire proving B5 did not open the barn door. |
| B8 | **The three benchmark jobs are re-run live on `claude -p`, with the user present, after the code lands.** New replay fixtures are recorded from those runs; the `agy` fixtures from the discarded attempt are not used. The M8N-0 §11 result in `DECISIONS.md` / `ROADMAP.md` / `IMPLEMENTATION_PLAN.md` is updated to the honest outcome. | The benchmark is the acceptance evidence; it must be produced on the real model through the real gates. |
| B9 | **If a job still fails a gate after B1–B6, that is the recorded result, not a trigger for more loosening.** M8N-0b fixes exactly the two validators named here. A third distinct gate failure is a new finding for a new scoped milestone. | The failure mode this milestone exists to correct is "loosen until green". One more turn of that screw is not the answer. |

## 4. S2 change in detail

`validate_s2_selection` (`src/tailor/s2.py`), the `covered` branch, today:

```python
if not any(_norm(entry.term) == _norm(keyword)
           for bid in entry.bullet_ids
           for keyword in bullets[bid].keywords_hit):
    raise S2ValidationError("covered term has no exact keyword hit")
```

Under B1–B3:

1. `components = _split_term(entry.term)` — split on `, and `, `, or `, `; `, ` / `, plain
   `, `, and standalone ` and `/` or ` (case-insensitive, Oxford comma included). A term with
   no match is `[entry.term]`.
2. `hits = { _norm(k) for bid in entry.bullet_ids for k in bullets[bid].keywords_hit }`.
3. `baseline = { _norm(t) for t in catalog.assumed_baseline_terms }`.
4. `required = [c for c in components if _norm(c) not in baseline]`.
5. If `required` is empty (all-baseline term): the entry must still cite ≥1 selected bullet
   (`entry.bullet_ids` non-empty and all in `covered`); otherwise `S2ValidationError`.
   No keyword-hit check for baseline components.
6. Else: every component in `required` must have `_norm(component) in hits`; otherwise
   `S2ValidationError("covered term has no exact keyword hit")` (message unchanged).

The `do_not_claim` block, the "cites unselected bullet" check, ordering, counts, and every
other S2 rule are untouched. `_split_term` is pure and unit-tested independently.

`SelectionCatalog` (`src/tailor/profile_views.py`) gains
`assumed_baseline_terms: tuple[str, ...]`. `selection_to_dict` emits it; `parse_selection`
requires it (not optional — the request always carries it, empty tuple when the file is
absent or empty). The list is loaded from `config/assumed_baseline_terms.txt` by the S2
request builder / pipeline, threaded through `run_stages`'s existing config-path parameters
(a new `assumed_baseline_terms_path: Path = Path("config/assumed_baseline_terms.txt")` beside
`banned_words_path` / `taste_path`, default-read, overridable in tests).

## 5. S3 change in detail

`_validate_bullet_edit` (`src/tailor/s3.py`), today:

```python
if len(plain_after) > len(source.plain_text):
    raise S3SemanticError(f"bullet_edits.{edit.bullet_id}: plain-text length grew")
```

Under B5:

```python
budget = max(len(t) for t in edit.motivating_terms)   # motivating_terms is non-empty (checked above)
if len(plain_after) > len(source.plain_text) + budget:
    raise S3SemanticError(f"bullet_edits.{edit.bullet_id}: plain-text length grew beyond the mirrored term")
```

The uncited-vocabulary check immediately below it is unchanged: any word in `plain_after` not
in `plain_before`, not in `motivating_words`, not a function word, not a digit still fails.
The leading-verb and numeric-token checks are unchanged. The `_synthetic_s2_request` catalog
construction in `s3.py` gains the new `assumed_baseline_terms` field as `()` (S3 never
consults it; it only needs `SelectionCatalog` to construct).

## 6. Repository boundary

| Path | M8N-0b may |
|---|---|
| `config/assumed_baseline_terms.txt` | create (new; one term per line; `#` comments allowed) |
| `src/tailor/s2.py` | add `_split_term`, rewrite the `covered` branch per §4 |
| `src/tailor/s3.py` | change the one length line per §5; add `assumed_baseline_terms=()` to the synthetic catalog |
| `src/tailor/profile_views.py` | add `assumed_baseline_terms` to `SelectionCatalog` + its to_dict/parse |
| `src/tailor/pilot.py` | thread `assumed_baseline_terms_path` through `run_stages`/`run_application` beside the other config paths |
| `src/tailor/lane.py` | pass the new path through if `run_manual_application` enumerates config paths (mirror `run_stages`) |
| `docs/prompts/tailoring_s2.md`, `docs/prompts/tailoring_s3.md` | one sentence each, per B4/B6, under N12 |
| `docs/DECISIONS.md`, `docs/ROADMAP.md`, `docs/IMPLEMENTATION_PLAN.md` | record B1–B9 and the honest M8N-0 §11 benchmark result |
| tests | new S2/S3 validator tests; a preflight assertion; replay fixtures + tests from the B8 live runs |
| `config/master_profile.yaml` | **never** |
| `src/tailor/invoke.py`, `scripts/score_batch.py` | **never** (no model-command change) |
| `src/tailor/g1.py`, `src/tailor/g2.py`, `src/tailor/g3.py` | **never** |

## 7. Testing strategy

- **No network, no DB, no model** in `pytest -q`, as always.
- **S2 (`tests/tailor/test_s2.py`):**
  - `_split_term` unit table (single term unchanged; `, and ` Oxford; `; `; ` / `; ` and `;
    ` or `; leading/trailing whitespace; empty parts dropped).
  - the job-225 case: compound term `data structures, algorithms, and distributed systems`,
    `data structures` + `algorithms` in `config/assumed_baseline_terms.txt`, a cited bullet
    whose `keywords_hit` contains `distributed systems` → `covered` accepted.
  - a compound term with a **non-baseline** component absent from every cited bullet →
    `S2ValidationError` (message unchanged), i.e. the guard still bites.
  - all-baseline term marked `covered` with `bullet_ids: []` → `S2ValidationError` (B3).
  - all-baseline term marked `gap` with `bullet_ids: []` → accepted (B3, the preferred answer).
  - a `do_not_claim` term as a compound component → still rejected when `covered`.
  - a single (non-compound) term → identical behavior to `c065756` (regression).
- **S3 (`tests/tailor/test_s3.py` / `test_trace_replay.py`):**
  - a mirror edit that grows by exactly one covered term's surface form → accepted.
  - `s3_length_growth_rejected.txt` → **still** `S3SemanticError ... length grew...` (B7).
  - an edit that grows beyond `max(len(motivating_term))` → rejected.
  - an edit adding an uncited word within the length budget → still rejected by the
    unchanged uncited-vocabulary guard (proves B5 did not weaken fabrication control).
- **Preflight:** `check_prompt_invariants(Path("docs/prompts"))` returns `()` after B4/B6;
  `run_preflight(..., skip_render=True).passed is True`.
- **Full suite** returns to green (the `c065756` baseline is 1916 passed, 1 deselected;
  M8N-0b adds tests, changes no existing assertion except where an existing test encodes the
  old S2/S3 rule and must be updated to the new rule with a comment citing B1/B5).
- **Live (B8, user-supervised):** jobs 225, 119, 211 via `tailor_now run` on `claude -p`;
  collect the §11 metrics table; record `m8n0b_<stage>_<job>_accepted.txt` replay fixtures.

## 8. Acceptance criteria

- `config/assumed_baseline_terms.txt` exists, is small, and is the only home of the baseline list.
- `DEFAULT_CLAUDE_CMD` is byte-identical to `c065756`. No file under §6's "never" row changed.
- S2 accepts the job-225 compound term with real per-component keyword hits; still rejects a
  compound term with an unevidenced non-baseline component; `do_not_claim` still blocked.
- S3 accepts a bounded terminology-mirror grow; `s3_length_growth_rejected.txt` still rejects;
  the uncited-vocabulary guard is unchanged and still bites.
- `check_prompt_invariants` clean; both prompt edits are the single enumerated sentences.
- `pytest -q` green apart from any pre-existing unrelated failure.
- `data/jobs.db` SHA-256 unchanged from
  `a9966f4afa4771b61e5b1838c9930e4c64062dc9d85d6fbb49cef17447843ae1`.
- The B8 live benchmark is run with the user; its result (per-job §11 table, pass or
  documented fail) is recorded in `DECISIONS.md`, and `ROADMAP.md` /
  `IMPLEMENTATION_PLAN.md` M8N status reflects it honestly.
- No push. Scoped commits `feat(m8n0b): …` / `fix(m8n0b): …` / `test(m8n0b): …` /
  `docs(m8n0b): …`.

## 9. Accepted trade-offs

- B1 makes S2 coverage matching more permissive for compound terms. Mitigation: every
  non-baseline component still needs a real curated keyword hit; the baseline list is small,
  reviewed, and in `config/`; B3 blocks all-baseline inflation.
- B5 lets an edited bullet grow. Mitigation: the growth is bounded by the mirrored term and
  the unchanged uncited-vocabulary guard means the added characters can only be that term;
  L4/L7/G2-C4 cap absolute size.
- The baseline list is a judgement call. It is a reviewable file the user owns; adding or
  removing a term is a one-line diff, not a code change.

## 10. Open items deferred

- Whether S1 should emit `components` per requirement so downstream stages never re-split
  (a cleaner but broader S1-contract change) — deferred; B1's validator-side split is the
  scoped fix.
- Any G1 keyword-density tuning (the "top-5 terms 2–3×" rule). It did not block jobs 225 or
  119 and is not touched here.
- The DB-fed pilot re-running its own benchmark against these corrected gates.
