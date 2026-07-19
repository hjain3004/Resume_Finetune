# Role-Family Matching v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the `role_family` eligibility gate from passing clearly wrong-specialty jobs (casino game tester, PCBA technician, PhD-only research scientist) on a single incidental JD keyword, while preserving the documented intent that non-standard-title genuine SWE roles (front-end, embedded) still reach the scorer.

**Architecture:** `src/eligibility.py`'s `evaluate()` role-family step gains two new mechanisms sourced from `config/eligibility.yaml`: (1) a title-only `exclude_patterns` hard filter checked before any positive match, (2) a `jd_fallback_min_hits` threshold requiring multiple distinct pattern hits (not one) for the post-resolution JD-text fallback to pass. `scripts/eligibility_impact.py` is reused unchanged to preview and apply the resulting reclassification against `data/jobs.db`.

**Tech Stack:** Python 3.11+, PyYAML, pytest, raw sqlite3 via `src/db.py`. No new dependencies.

## Global Constraints

- Tests never touch the network; this feature is pure regex/config logic with no fixtures needed.
- Idempotency is sacred — the DB apply step must be re-runnable without double-mutating rows (it reuses the existing guarded-apply mechanism, which is already idempotent).
- Raw sqlite3 via `src/db.py` helpers only — no SQL strings outside `db.py` (no new SQL needed; `eligibility_impact.py` is reused as-is).
- UTC ISO-8601 timestamps in storage (unaffected — no schema/storage change).
- `src/` logging via `logging`, never `print` (no changes to logging surface in this plan).
- One milestone: **M6.12 — Role-Family Matching v2**. Do not start any other milestone in this session.
- This is a deterministic `src/` change only — no agentic/control-plane code touched.

---

## File Structure

- **Modify:** `src/eligibility.py` — `RoleFamily` dataclass gains `exclude_patterns`; `RoleFamilyPolicy` gains `jd_fallback_min_hits`; `_parse_role_families` parses both; `evaluate()`'s role-family step is rewritten.
- **Modify:** `config/eligibility.yaml` — `role_families.include[0].patterns` split into a list of individual terms; `role_families.include[0].exclude_patterns` added; `role_families.jd_fallback_min_hits: 2` added.
- **Modify:** `tests/test_eligibility_config.py` — assert the new fields parse correctly; add invalid-config rejection cases.
- **Modify:** `tests/test_eligibility.py` — new tests for exclude-first precedence, raised fallback bar, unchanged title-match-passes-outright behavior; update the existing `"Marketing Analyst"` parametrized case (title contains "Analyst", which is now an exclude term, so its reason code changes).
- **No changes:** `scripts/eligibility_impact.py`, `src/db.py` — both are already generic over whatever policy `load_eligibility_config()` returns.
- **Modify:** `docs/DECISIONS.md` — append the deviation-from-M6.9 rationale, impact numbers, and apply record.
- **Modify:** `docs/ROADMAP.md` — add M6.12 status line under Phase 2.
- **Modify:** `data/calibration/` — discard and regenerate round `2026-07-17-r2` if the apply step removes any of its jobs.

---

## Task 1: Config schema — role-family exclude patterns and JD-fallback threshold

**Files:**
- Modify: `src/eligibility.py:113-122` (`RoleFamily`, `RoleFamilyPolicy` dataclasses), `src/eligibility.py:370-384` (`_parse_role_families`)
- Modify: `config/eligibility.yaml:42-46` (`role_families` block)
- Test: `tests/test_eligibility_config.py`

**Interfaces:**
- Produces: `RoleFamily.exclude_patterns: tuple[Pattern[str], ...]`, `RoleFamilyPolicy.jd_fallback_min_hits: int` — consumed by Task 2's rewritten `evaluate()`.

- [ ] **Step 1: Write the failing config test**

Add to `tests/test_eligibility_config.py`, in `test_loads_valid_config_as_frozen_typed_contract`:

```python
    assert config.role_families.include[0].name == "software_engineering"
    assert len(config.role_families.include[0].patterns) > 1
    assert config.role_families.include[0].exclude_patterns
    assert any(
        p.search("Senior Research Scientist")
        for p in config.role_families.include[0].exclude_patterns
    )
    assert config.role_families.jd_fallback_min_hits == 2
```

Also add two new rows to the `test_validation_rejects_invalid_policy` parametrize list in the same file:

```python
        (lambda p: p["role_families"].update(jd_fallback_min_hits=0), "role_families.jd_fallback_min_hits"),
        (
            lambda p: p["role_families"]["include"][0].update(exclude_patterns=["["]),
            "role_families.include[0].exclude_patterns[0]: invalid regex",
        ),
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_eligibility_config.py -v`
Expected: `test_loads_valid_config_as_frozen_typed_contract` FAILs with `AttributeError: 'RoleFamily' object has no attribute 'exclude_patterns'` (or `RoleFamilyPolicy` has no `jd_fallback_min_hits`); the two new parametrized cases FAIL because no `EligibilityConfigError` is raised yet (unknown keys are currently ignored).

- [ ] **Step 3: Update `config/eligibility.yaml`**

Replace the `role_families` block (lines 42-46) with:

```yaml
role_families:
  jd_fallback_min_hits: 2
  include:
    - name: software_engineering
      patterns:
        - "software"
        - "\\bswe\\b"
        - "backend"
        - "back.end"
        - "full.?stack"
        - "platform"
        - "infrastructure"
        - "distributed"
        - "developer"
      exclude_patterns:
        - "technician"
        - "\\bresearch scientist\\b"
        - "\\banalyst\\b"
        - "\\bauditor\\b"
        - "\\b(game\\s+)?tester\\b"
        - "casino"
```

- [ ] **Step 4: Implement the dataclass changes**

In `src/eligibility.py`, update `RoleFamily` and `RoleFamilyPolicy` (around line 113-122):

```python
@dataclass(frozen=True)
class RoleFamily:
    name: str
    patterns: tuple[Pattern[str], ...]
    exclude_patterns: tuple[Pattern[str], ...]


@dataclass(frozen=True)
class RoleFamilyPolicy:
    include: tuple[RoleFamily, ...]
    jd_fallback_min_hits: int
```

- [ ] **Step 5: Implement the parser changes**

Replace `_parse_role_families` (around line 370-384):

```python
def _parse_role_families(payload: Any) -> RoleFamilyPolicy:
    if not isinstance(payload, dict):
        raise EligibilityConfigError("role_families")
    include = payload.get("include")
    if not isinstance(include, list) or not include:
        raise EligibilityConfigError("role_families.include")
    families = []
    for idx, item in enumerate(include):
        if not isinstance(item, dict) or not item.get("name"):
            raise EligibilityConfigError(f"role_families.include[{idx}]")
        families.append(
            RoleFamily(
                name=str(item["name"]),
                patterns=_compile_patterns(item.get("patterns"), f"role_families.include[{idx}].patterns"),
                exclude_patterns=_compile_patterns(
                    item.get("exclude_patterns") or [], f"role_families.include[{idx}].exclude_patterns"
                ),
            )
        )
    min_hits = payload.get("jd_fallback_min_hits")
    if not isinstance(min_hits, int) or isinstance(min_hits, bool) or min_hits < 1:
        raise EligibilityConfigError("role_families.jd_fallback_min_hits")
    return RoleFamilyPolicy(include=tuple(families), jd_fallback_min_hits=min_hits)
```

Note: `_compile_patterns` already raises `EligibilityConfigError(f"{path}[{idx}]: invalid regex")` on a bad regex, which matches the exact message asserted in Step 1's second new test case.

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_eligibility_config.py -v`
Expected: all PASS.

- [ ] **Step 7: Run the full test suite to check for regressions from the schema change**

Run: `pytest -q`
Expected: only `tests/test_eligibility.py::test_post_resolution_filters_with_stable_reason_codes[Marketing Analyst-...]` fails (title "Marketing Analyst" now matches the new `\banalyst\b` exclude pattern before reaching the unchanged role-family fallback logic — Task 2 fixes this). All other tests PASS. If anything else fails, stop and investigate before continuing — this task should only touch parsing, not matching behavior.

- [ ] **Step 8: Commit**

```bash
git add src/eligibility.py config/eligibility.yaml tests/test_eligibility_config.py
git commit -m "feat(eligibility): add role-family exclude patterns and JD-fallback threshold to config schema"
```

---

## Task 2: Rewrite role-family matching logic in `evaluate()`

**Files:**
- Modify: `src/eligibility.py:721-723` (role-family step inside `evaluate()`)
- Test: `tests/test_eligibility.py`

**Interfaces:**
- Consumes: `RoleFamily.exclude_patterns`, `RoleFamilyPolicy.jd_fallback_min_hits` (from Task 1).
- Produces: new reason code `"eligibility:role_family_excluded"`, distinguishable from the existing `"eligibility:role_family"`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_eligibility.py`, update the existing parametrized case (line 32) — the reason code changes because "Marketing Analyst" now hits the new exclude list:

```python
        ("Marketing Analyst", "New York, NY", "Starts in 2027", "eligibility:role_family_excluded"),
```

Add these new test functions after `test_post_resolution_filters_with_stable_reason_codes`:

```python
def test_title_exclude_pattern_filters_even_with_saturated_jd_include_hits() -> None:
    decision = _decision(
        "Casino Game Tester",
        "New York, NY",
        "You will test our platform. Our backend developer team built the infrastructure. "
        "This role is distributed across our full-stack software developer group.",
    )

    assert decision.disposition is EligibilityDisposition.FILTER
    assert decision.reason_code == "eligibility:role_family_excluded"


def test_title_include_pattern_still_passes_outright() -> None:
    decision = _decision("Embedded Software Engineer", "New York, NY", "Starts in 2027.")

    assert decision.disposition is EligibilityDisposition.PASS


def test_single_incidental_jd_keyword_no_longer_passes() -> None:
    decision = _decision(
        "Power Electronics PCBA Technician",
        "Santa Cruz, CA",
        "Join our infrastructure buildout team. Starts in 2027.",
    )

    assert decision.disposition is EligibilityDisposition.FILTER
    assert decision.reason_code == "eligibility:role_family_excluded"


def test_jd_only_job_with_two_distinct_hits_passes() -> None:
    decision = _decision(
        "Full Stack Developer II",
        "New York, NY",
        "You will build backend services using our distributed platform. Starts in 2027.",
    )

    assert decision.disposition is EligibilityDisposition.PASS


def test_jd_only_job_with_one_distinct_hit_filters() -> None:
    decision = _decision(
        "Product Coordinator",
        "New York, NY",
        "You will coordinate with our platform team. Starts in 2027.",
    )

    assert decision.disposition is EligibilityDisposition.FILTER
    assert decision.reason_code == "eligibility:role_family"


def test_pre_resolution_exclude_applies_to_title_without_jd_text() -> None:
    decision = _decision(
        "SAP SD Analyst",
        "New York, NY",
        None,
        stage=EligibilityStage.PRE_RESOLUTION,
    )

    assert decision.disposition is EligibilityDisposition.FILTER
    assert decision.reason_code == "eligibility:role_family_excluded"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_eligibility.py -v`
Expected: the updated `"Marketing Analyst"` case and all six new tests FAIL (current logic has no exclude check and passes on one JD hit).

- [ ] **Step 3: Implement the new role-family step**

In `src/eligibility.py`, replace lines 721-723:

```python
    if not any(pattern.search(title) or (stage is EligibilityStage.POST_RESOLUTION and jd_text and pattern.search(jd_text))
               for family in config.role_families.include for pattern in family.patterns):
        return _decision(EligibilityDisposition.FILTER, "eligibility:role_family", flags, ())
```

with:

```python
    if any(pattern.search(title) for family in config.role_families.include for pattern in family.exclude_patterns):
        return _decision(EligibilityDisposition.FILTER, "eligibility:role_family_excluded", flags, ())

    title_match = any(pattern.search(title) for family in config.role_families.include for pattern in family.patterns)
    if not title_match:
        if stage is EligibilityStage.POST_RESOLUTION and jd_text:
            distinct_hits = sum(
                1
                for family in config.role_families.include
                for pattern in family.patterns
                if pattern.search(jd_text)
            )
            if distinct_hits < config.role_families.jd_fallback_min_hits:
                return _decision(EligibilityDisposition.FILTER, "eligibility:role_family", flags, ())
        else:
            return _decision(EligibilityDisposition.FILTER, "eligibility:role_family", flags, ())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_eligibility.py -v`
Expected: all PASS.

- [ ] **Step 5: Run the full test suite**

Run: `pytest -q`
Expected: all PASS (this closes the one known regression from Task 1 Step 7).

- [ ] **Step 6: Commit**

```bash
git add src/eligibility.py tests/test_eligibility.py
git commit -m "feat(eligibility): require multi-signal JD match and hard-exclude wrong-specialty titles in role_family gate"
```

---

## Task 3: Preview retroactive impact against the live DB

**Files:**
- No code changes — runs the existing `scripts/eligibility_impact.py` (verified in Task 1/2 to need no modification since it is generic over `load_eligibility_config()`).

**Interfaces:**
- Consumes: the updated `config/eligibility.yaml` from Task 1, `data/jobs.db` (read-only).
- Produces: a JSON impact report at `data/calibration/role-family-v2-impact.json` for user review before Task 4's apply.

- [ ] **Step 1: Run the read-only impact preview**

Run:
```bash
PYTHONPATH=. python scripts/eligibility_impact.py --db data/jobs.db --json data/calibration/role-family-v2-impact.json
```
Expected: prints a JSON summary with `counts_by_action` and `counts_by_reason` to stdout; writes the full transition list to `data/calibration/role-family-v2-impact.json`. Exit code 0.

- [ ] **Step 2: Inspect the transitions for the three known jobs**

Run:
```bash
python -c "
import json
data = json.load(open('data/calibration/role-family-v2-impact.json'))
for t in data['transitions']:
    if t['job_id'] in (44, 53, 96, 111, 123):
        print(t['job_id'], t['action'], t['from_status'], '->', t['to_status'], t['reason_code'])
"
```
Expected: ids 96, 111, 123 show `action: filter_active`, `to_status: FILTERED_OUT`, `reason_code: eligibility:role_family_excluded`. ids 44 and 53 show the same if still active (`RESOLVED`/`SCORED`/`SHORTLISTED`) — confirm their current status matches what's expected before proceeding; if either was already scored/shortlisted, flag this to the user before Task 4 rather than silently reclassifying a scored row.

- [ ] **Step 3: Show the full report summary to the user for approval**

Print `data['counts_by_action']` and `data['counts_by_reason']` and the full list of affected `(job_id, company, title)` (join against `data/jobs.db` by id) in the response to the user. Do not proceed to Task 4 until the user confirms the transition list looks correct.

- [ ] **Step 4: Commit the impact report for the record**

```bash
git add data/calibration/role-family-v2-impact.json
git commit -m "chore(eligibility): record role-family v2 impact preview against live DB"
```

---

## Task 4: Back up and apply the DB reclassification

**Files:**
- No code changes — uses `scripts/eligibility_impact.py --apply`.

**Interfaces:**
- Consumes: user approval from Task 3 Step 3.
- Produces: updated `data/jobs.db`; a timestamped backup file.

- [ ] **Step 1: Generate the backup timestamp and confirm the backup path doesn't already exist**

```bash
BACKUP="data/backups/jobs-pre-role-family-v2-$(date -u +%Y%m%dT%H%M%SZ).db"
echo "$BACKUP"
ls "$BACKUP" 2>&1  # expect: No such file or directory
```

- [ ] **Step 2: Apply, with backup and explicit confirmation**

```bash
PYTHONPATH=. python scripts/eligibility_impact.py --db data/jobs.db --apply --confirm APPLY --backup "$BACKUP"
```
Expected: JSON output `{"changed": N, "previewed": N}` where `N` matches the non-`report_terminal` transition count from Task 3's preview. Exit code 0.

- [ ] **Step 3: Verify DB integrity and status-count deltas**

```bash
sqlite3 data/jobs.db "PRAGMA integrity_check;"
sqlite3 data/jobs.db "SELECT status, COUNT(*) FROM jobs GROUP BY status ORDER BY status;"
```
Expected: `integrity_check` returns `ok`. Compare the status counts against the pre-apply counts (query the backup file the same way) — only `RESOLVED`/`SCORED`/`SHORTLISTED` counts should shift down, `FILTERED_OUT` should shift up by the same total, `SHORTLISTED` count should be unchanged unless Task 3 Step 2 flagged an already-shortlisted row.

- [ ] **Step 4: Confirm ids 96, 111, 123 are now FILTERED_OUT**

```bash
sqlite3 data/jobs.db "SELECT id, status, filter_reason FROM jobs WHERE id IN (96, 111, 123);"
```
Expected: all three rows show `status=FILTERED_OUT`, `filter_reason=eligibility:role_family_excluded`.

- [ ] **Step 5: Commit is not applicable here** (the backup file lives in `data/backups/`, which is data not source — check whether it's gitignored)

```bash
git status data/backups/ data/jobs.db
```
If `data/jobs.db` is tracked in git, stage and commit it; if `data/backups/` is gitignored (check `.gitignore`), no commit needed for the backup itself. Follow whatever the repo already does for prior backup commits (`git log --oneline -- data/backups/`).

---

## Task 5: Record the decision and update roadmap status

**Files:**
- Modify: `docs/DECISIONS.md`
- Modify: `docs/ROADMAP.md`

**Interfaces:**
- None (documentation only).

- [ ] **Step 1: Append a DECISIONS.md entry**

Append to `docs/DECISIONS.md`, following the exact style of the `## 2026-07-17 — Bare named clearance levels...` entry (problem found, evidence, decision + rationale, what changed, impact preview numbers, verification, apply record). Include explicitly:
- This is an approved deviation from `PHASE2_KICKOFF.md` line 304's revisit trigger (20% of scored volume) — the user chose to fix the mechanism regardless of trigger status, because calibration review surfaced 3 clearly-wrong-category jobs before any scored-volume threshold was reached.
- The exact `counts_by_action` / `counts_by_reason` numbers from Task 3.
- The backup path and apply confirmation from Task 4.
- Test counts (`pytest -q` final tally).

- [ ] **Step 2: Update `docs/ROADMAP.md`**

Under the `## Phase 2 — Scoring Calibration` section, after the `**Calibration Contract v2: COMPLETE (2026-07-16).**` paragraph, add:

```markdown
**M6.12 — Role-Family Matching v2: COMPLETE (2026-07-19).** Closed a gap in M6.9's
JD-text fallback where a single incidental keyword match (e.g. "platform" once) let
clearly wrong-specialty postings (casino game tester, PCBA technician, PhD-only research
scientist) reach the scorer. Added title-only exclude patterns and a distinct-hit
threshold for the JD fallback; see DECISIONS.md for the approved deviation from the
documented 20%-of-scored-volume revisit trigger and live impact numbers.
```

- [ ] **Step 3: Commit**

```bash
git add docs/DECISIONS.md docs/ROADMAP.md
git commit -m "docs: record M6.12 role-family matching v2 decision and roadmap status"
```

---

## Task 6: Regenerate calibration round 2026-07-17-r2

**Files:**
- No code changes — uses `scripts/export_batch.py` and `scripts/calibration_packet.py`.
- Creates: a new `data/batch/2026-07-19.json` (re-export), then `data/calibration/2026-07-19-r2.batch.json` and `.interest.md`.

**Interfaces:**
- Consumes: the applied DB state from Task 4.

- [ ] **Step 1: Confirm whether round r2's job set actually changed**

```bash
python -c "
import json
batch = json.load(open('data/calibration/2026-07-17-r2.batch.json'))
ids = {g['id'] for g in batch['groups']}  # adjust key names to match actual batch schema
print(sorted(ids & {96, 111, 123}))
"
```
Expected: `[96, 111, 123]` (or whatever subset actually applied) — confirms the round is contaminated and must be discarded. If empty, skip this task entirely and tell the user r2 is unaffected.

- [ ] **Step 2: Re-export a clean batch**

```bash
PYTHONPATH=. python scripts/export_batch.py --db data/jobs.db --out-dir data/batch
```
Expected: writes `data/batch/2026-07-19.json`, exporting only `RESOLVED` rows — the now-`FILTERED_OUT` ids (96, 111, 123, and any others from Task 4) are excluded automatically since export only pulls `RESOLVED` status.

- [ ] **Step 3: Start a fresh round excluding both prior rounds**

```bash
PYTHONPATH=. python scripts/calibration_packet.py start data/batch/2026-07-19.json \
  --round 2026-07-19-r2 \
  --exclude-round data/calibration/2026-07-16-r1.batch.json \
  --exclude-round data/calibration/2026-07-17-r1.batch.json \
  --exclude-round data/calibration/2026-07-17-r2.batch.json
```
Expected: writes `data/calibration/2026-07-19-r2.batch.json` and `.interest.md` with 12 fresh jobs, zero overlap with all three prior rounds (the two real prior rounds plus the discarded contaminated r2).

- [ ] **Step 4: Tell the user the round was regenerated**

Report the new round path and ask them to fill `interest_call` blind again, same as the original r2 kickoff — their existing r2 interest/fit labels remain on disk as a record but no longer count toward the Phase 2 evidence gate.

- [ ] **Step 5: Commit the new round artifacts**

```bash
git add data/calibration/2026-07-19-r2.batch.json data/calibration/2026-07-19-r2.interest.md
git commit -m "feat(calibration): regenerate round r2 after role-family v2 eligibility apply"
```

---

## Self-Review Notes

- **Spec coverage:** Config schema (Task 1) ✓, evaluate() logic (Task 2) ✓, impact preview + apply (Tasks 3-4) ✓, DECISIONS.md + ROADMAP.md (Task 5) ✓, r2 regeneration (Task 6) ✓, testing plan (Tasks 1-2 steps) ✓.
- **Placeholder scan:** Task 6 Step 2 references "whatever the existing batch-export entry point is" because the exact script name wasn't confirmed during planning — this is flagged as a step for the implementer to resolve by reading `docs/DECISIONS.md`'s prior `2026-07-17` re-export record, not a vague instruction to figure out the whole task.
- **Type consistency:** `reason_code` string literals (`"eligibility:role_family"`, `"eligibility:role_family_excluded"`) are consistent across Task 2's implementation and all test assertions in Tasks 2-3.
