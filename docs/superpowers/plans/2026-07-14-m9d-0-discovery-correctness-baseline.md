# M9D-0 Discovery Correctness & Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make tracker checkpoints incapable of advancing ahead of durable job insertion, preserve deferred jobs under `--limit`, distinguish source failure from legitimate zero yield, and record the pre-expansion source/backlog baseline.

**Architecture:** Discovery becomes a two-phase prepare/commit protocol. Adapters return immutable jobs plus a pending checkpoint; `run_ingest` inserts the jobs first and only then atomically replaces snapshots. A read-only command derives the baseline from existing `runs`, `run_sources`, and `jobs` tables, so M9D-0 adds no schema.

**Tech Stack:** Python 3.11+, stdlib dataclasses/JSON/pathlib/sqlite3, existing requests/PyYAML/pytest. No new dependency.

## Global Constraints

- Implement M9D-0 only. Do not begin M9D-1 through M9D-5.
- Tests never touch the network; use existing fixtures and mocked adapters.
- A checkpoint may lag SQLite after a crash; it must never lead SQLite.
- Snapshot replacement is sibling-temp-file plus `os.replace`.
- `--limit N` is per source; deferred keys stay eligible through `pending_keys`.
- Legacy `{keys, source_path}` snapshots load with empty `pending_keys`.
- Preserve source ordering, dedup/source-priority behavior, status transitions, and etiquette.
- No raw SQL outside `src/db.py`; no dependency or DB-schema change.
- Do not stage or modify the user's existing `tests/test_scoring_stress.py` change.
- Use `.venv/bin/pytest`, not global `pytest`.

## Confirmed defects

1. `tracker_common.diff_new_jobs()` overwrites a snapshot before `db.insert_discovered()`.
2. `discover_all()` slices for `--limit` after that overwrite, so uninserted rows can be
   marked seen even on a successful run.
3. Adapter exceptions are logged and discarded, making a crash look like a valid zero.
4. Existing source counters have no reproducible read-only baseline report.

## File map

Create:

- `tests/test_discovery_checkpoint.py`
- `scripts/source_baseline.py`
- `tests/test_source_baseline.py`

Modify:

- `src/discover/base.py`, `src/discover/tracker_common.py`
- all three `src/discover/tracker_*.py` adapters and `src/discover/__init__.py`
- `src/run_ingest.py`, `src/db.py`, `src/digest.py`
- tracker/registry/run-ingest/digest tests
- authoritative architecture, self-healing, roadmap, upgrade, and decision docs

---

### Task 1: Pure prepare/commit checkpoint protocol

**Files:**
- Modify: `src/discover/base.py:1-13`
- Modify: `src/discover/tracker_common.py:225-264`
- Create: `tests/test_discovery_checkpoint.py`

**Interfaces:**
- Produces `SnapshotState`, `PendingCheckpoint`, `AdapterDiscovery`, `DiscoveryIssue`,
  `DiscoveryResult`.
- Produces `prepare_snapshot_diff(...) -> AdapterDiscovery` and
  `commit_checkpoint(PendingCheckpoint) -> None`.

- [ ] **Step 1: Write failing protocol tests**

Create `tests/test_discovery_checkpoint.py` with these complete behaviors:

```python
import json
import os
import pytest

from src.discover import tracker_common
from src.models import DiscoveredJob, dedup_key


def job(n):
    return DiscoveredJob(
        f"Company {n}", f"SWE {n}", "Remote",
        f"https://example.com/{n}", "tracker_test", None,
    )


def key(n):
    item = job(n)
    return dedup_key(item.company, item.title, item.location)


def test_prepare_is_side_effect_free(tmp_path):
    result = tracker_common.prepare_snapshot_diff(
        [job(1)], tmp_path, "listings.json", "tracker_test"
    )
    assert result.jobs == (job(1),)
    assert not (tmp_path / "tracker_test.json").exists()


def test_legacy_snapshot_has_no_pending_keys(tmp_path):
    path = tmp_path / "tracker_test.json"
    path.write_text(json.dumps({"keys": [key(1)], "source_path": "old.json"}))
    state = tracker_common.load_snapshot_state(tmp_path, "tracker_test")
    result = tracker_common.prepare_snapshot_diff(
        [job(1), job(2)], tmp_path, "new.json", "tracker_test"
    )
    assert state.pending_keys == frozenset()
    assert result.jobs == (job(2),)
    assert "pending_keys" not in json.loads(path.read_text())


def test_limit_drains_deferred_keys_across_runs(tmp_path):
    items = [job(1), job(2), job(3)]
    expected = [job(1), job(2), job(3)]
    for wanted in expected:
        prepared = tracker_common.prepare_snapshot_diff(
            items, tmp_path, "listings.json", "tracker_test", limit=1
        )
        assert prepared.jobs == (wanted,)
        tracker_common.commit_checkpoint(prepared.checkpoint)
    assert tracker_common.prepare_snapshot_diff(
        items, tmp_path, "listings.json", "tracker_test", limit=1
    ).jobs == ()


def test_prepare_deduplicates_one_fetch(tmp_path):
    assert tracker_common.prepare_snapshot_diff(
        [job(1), job(1)], tmp_path, "listings.json", "tracker_test"
    ).jobs == (job(1),)


def test_replace_failure_preserves_old_snapshot(tmp_path, monkeypatch):
    path = tmp_path / "tracker_test.json"
    old = {"keys": ["old"], "pending_keys": [], "source_path": "old.json"}
    path.write_text(json.dumps(old))
    prepared = tracker_common.prepare_snapshot_diff(
        [job(1)], tmp_path, "new.json", "tracker_test"
    )
    monkeypatch.setattr(os, "replace", lambda *_: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError, match="disk"):
        tracker_common.commit_checkpoint(prepared.checkpoint)
    assert json.loads(path.read_text()) == old
    assert list(tmp_path.glob(".tracker_test.json.*.tmp")) == []
```

- [ ] **Step 2: Verify red**

Run: `.venv/bin/pytest tests/test_discovery_checkpoint.py -v`

Expected: missing-type/function failures.

- [ ] **Step 3: Replace `src/discover/base.py` contracts**

```python
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from src.models import DiscoveredJob


@dataclass(frozen=True)
class SnapshotState:
    keys: frozenset[str]
    pending_keys: frozenset[str]


@dataclass(frozen=True)
class PendingCheckpoint:
    source: str
    path: Path
    source_path: str
    keys: frozenset[str]
    pending_keys: frozenset[str]


@dataclass(frozen=True)
class AdapterDiscovery:
    source: str
    jobs: tuple[DiscoveredJob, ...]
    checkpoint: PendingCheckpoint | None


@dataclass(frozen=True)
class DiscoveryIssue:
    source: str
    stage: str
    error_type: str
    message: str


@dataclass(frozen=True)
class DiscoveryResult:
    jobs: tuple[DiscoveredJob, ...]
    checkpoints: tuple[PendingCheckpoint, ...]
    succeeded_sources: tuple[str, ...]
    issues: tuple[DiscoveryIssue, ...]


class DiscoverAdapter(Protocol):
    SOURCE_NAME: str
    def discover(self, config: dict) -> AdapterDiscovery: ...
```

- [ ] **Step 4: Add checkpoint preparation/commit without breaking old callers**

Add `os` and `uuid` imports in `tracker_common.py`; import Task 1 types. Replace snapshot
state loading with the wrapper below, and add the new preparation/commit functions alongside
the existing `save_snapshot_keys()` and `diff_new_jobs()`. Those two unsafe compatibility
functions stay temporarily so Task 1's commit keeps the existing suite green; Task 2 removes
them after all adapters switch.

```python
def load_snapshot_state(snapshot_dir, source_name):
    path = _snapshot_path(snapshot_dir, source_name)
    if not path.exists():
        return SnapshotState(frozenset(), frozenset())
    payload = json.loads(path.read_text())
    return SnapshotState(
        frozenset(payload.get("keys", [])),
        frozenset(payload.get("pending_keys", [])),
    )


def load_snapshot_keys(snapshot_dir, source_name):
    return set(load_snapshot_state(snapshot_dir, source_name).keys)


def prepare_snapshot_diff(jobs, snapshot_dir, source_path, source_name, *, limit=None):
    previous = load_snapshot_state(snapshot_dir, source_name)
    current_keys, candidate_keys, candidates = set(), set(), []
    for item in jobs:
        item_key = dedup_key(item.company, item.title, item.location)
        current_keys.add(item_key)
        if item_key in candidate_keys:
            continue
        if item_key not in previous.keys or item_key in previous.pending_keys:
            candidate_keys.add(item_key)
            candidates.append(item)
    selected = candidates if limit is None else candidates[:limit]
    deferred = candidates[len(selected):]
    checkpoint = PendingCheckpoint(
        source_name,
        _snapshot_path(snapshot_dir, source_name),
        source_path,
        frozenset(current_keys),
        frozenset(dedup_key(j.company, j.title, j.location) for j in deferred),
    )
    return AdapterDiscovery(source_name, tuple(selected), checkpoint)


def commit_checkpoint(checkpoint):
    path = checkpoint.path
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    payload = {
        "keys": sorted(checkpoint.keys),
        "pending_keys": sorted(checkpoint.pending_keys),
        "source_path": checkpoint.source_path,
    }
    try:
        temporary.write_text(json.dumps(payload, indent=2) + "\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
```

- [ ] **Step 5: Verify new and legacy tests stay green, then commit**

Run:

```bash
.venv/bin/pytest tests/test_discovery_checkpoint.py tests/test_tracker_vansh.py \
  tests/test_tracker_simplify.py tests/test_tracker_jobright.py -v
```

Expected: all selected tests pass; existing adapters still work until Task 2 migrates them.

```bash
git add src/discover/base.py src/discover/tracker_common.py tests/test_discovery_checkpoint.py
git commit -m "feat(m9d-0): add prepared discovery checkpoints"
```

---

### Task 2: Refactor trackers and registry to prepared results

**Files:**
- Modify: all three `src/discover/tracker_*.py` adapters
- Modify: `src/discover/tracker_common.py`, `src/discover/__init__.py`
- Modify: `tests/test_tracker_{vansh,simplify,jobright}.py`, `tests/test_discover_all.py`

**Interfaces:**
- Consumes `prepare_snapshot_diff`.
- Produces `discover(config) -> AdapterDiscovery` for each adapter.
- Produces `discover_all(...) -> DiscoveryResult`.

- [ ] **Step 1: Rewrite registry tests for explicit jobs/checkpoints/issues**

Use a fake adapter returning `AdapterDiscovery`; tests must assert:

```python
def test_failure_is_preserved_and_other_source_succeeds():
    result = discover_all(config, adapters={"good": good_adapter, "bad": bad_adapter})
    assert result.succeeded_sources == ("good",)
    assert result.issues == (
        DiscoveryIssue("bad", "fetch", "RuntimeError", "boom"),
    )


def test_limit_is_passed_to_adapter():
    result = discover_all(config, limit=2, adapters={"good": limit_aware_adapter})
    assert len(result.jobs) == 2


def test_checkpoint_is_returned_but_not_written(tmp_path):
    result = discover_all(config, adapters={"good": checkpoint_adapter(tmp_path)})
    assert len(result.checkpoints) == 1
    assert not result.checkpoints[0].path.exists()
```

Retain the cross-source priority test, inserting `list(result.jobs)` into the temp DB.

- [ ] **Step 2: Verify red**

Run: `.venv/bin/pytest tests/test_discover_all.py -v`

Expected: old list return and missing injectable registry fail.

- [ ] **Step 3: Refactor each tracker**

Delete its `diff_new_jobs` wrapper, `dedup_key` import, and dry-run branch. Preserve fetch and
parse logic, then return:

```python
return common.prepare_snapshot_diff(
    jobs,
    snapshot_dir,
    source_path,  # combined_source_path for Jobright
    SOURCE_NAME,
    limit=config.get("limit"),
)
```

- [ ] **Step 4: Replace registry aggregation**

Add an optional `adapters` seam for tests and aggregate immutable results:

```python
def discover_all(sources_cfg, *, limit=None, dry_run=False, adapters=None):
    registry = ADAPTERS if adapters is None else adapters
    jobs, checkpoints, succeeded, issues = [], [], [], []
    for name, cfg in sources_cfg.items():
        if not cfg.get("enabled") or name not in registry:
            continue
        try:
            prepared = registry[name].discover(dict(cfg, dry_run=dry_run, limit=limit))
        except Exception as exc:
            logger.exception("discovery failed for source %s", name)
            issues.append(DiscoveryIssue(name, "fetch", type(exc).__name__, str(exc)[:500]))
            continue
        jobs.extend(prepared.jobs)
        if prepared.checkpoint is not None:
            checkpoints.append(prepared.checkpoint)
        succeeded.append(name)
    return DiscoveryResult(tuple(jobs), tuple(checkpoints), tuple(succeeded), tuple(issues))
```

- [ ] **Step 5: Remove the unsafe API and update tracker tests**

After `rg -n "diff_new_jobs|save_snapshot_keys" src` shows no callers, delete those functions.
Tracker tests must call `prepare_snapshot_diff`, assert no file exists, explicitly call
`commit_checkpoint`, then assert the next fixture yields only its two added rows.

- [ ] **Step 6: Verify discovery suite and commit**

```bash
.venv/bin/pytest tests/test_discovery_checkpoint.py tests/test_discover_all.py \
  tests/test_tracker_vansh.py tests/test_tracker_simplify.py \
  tests/test_tracker_jobright.py -v
git add src/discover tests/test_discover_all.py tests/test_tracker_vansh.py \
  tests/test_tracker_simplify.py tests/test_tracker_jobright.py
git commit -m "refactor(m9d-0): separate discovery from checkpoint commit"
```

Expected: selected tests pass; no adapter mutates snapshots.

---

### Task 3: Insert first, commit second, surface failures

**Files:**
- Modify: `src/run_ingest.py:20-247`, `src/digest.py:165-238`
- Modify: `tests/test_run_ingest_sources.py`, `tests/test_digest.py`

**Interfaces:**
- Produces `persist_discovery(...) -> (inserted_by_source, checkpoint_issues)`.
- Produces JSON `runs.notes`: `{"discovery_issues": [{source, stage, error_type, message}]}`.
- Produces CLI `--snapshot-dir DIR` for isolated smoke runs.

- [ ] **Step 1: Write failing persistence tests**

Add tests using a real in-memory DB and a `DiscoveryResult` with one checkpoint:

```python
def test_db_failure_never_calls_checkpoint_commit(tmp_path):
    with patch.object(db, "insert_discovered", side_effect=RuntimeError("db")):
        with patch.object(run_ingest.tracker_common, "commit_checkpoint") as commit:
            with pytest.raises(RuntimeError, match="db"):
                run_ingest.persist_discovery(conn, result, stale_days=21,
                                             reopen_days=45, dry_run=False)
    commit.assert_not_called()


def test_checkpoint_failure_keeps_inserted_row_and_returns_issue(tmp_path):
    with patch.object(run_ingest.tracker_common, "commit_checkpoint",
                      side_effect=OSError("disk")):
        inserted, issues = run_ingest.persist_discovery(
            conn, result, stale_days=21, reopen_days=45, dry_run=False
        )
    assert inserted == {"tracker_vansh": 1}
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
    assert issues[0].stage == "checkpoint"


def test_dry_run_never_commits_checkpoint(tmp_path):
    with patch.object(run_ingest.tracker_common, "commit_checkpoint") as commit:
        run_ingest.persist_discovery(conn, result, stale_days=21,
                                     reopen_days=45, dry_run=True)
    commit.assert_not_called()
```

Add main-level tests:

- all selected adapters fail -> exit 1, `runs.finished_at` set, structured notes stored;
- one succeeds/one fails -> exit 0, failed source remains visible in notes;
- `--resolve-only` does not falsely return 1;
- `--snapshot-dir` reaches each selected adapter config.

- [ ] **Step 2: Add failing digest warning test**

Seed `runs.notes` with one issue and assert digest contains:

```text
### Run warnings
- tracker_simplify [fetch/RuntimeError]: boom
```

- [ ] **Step 3: Verify red**

Run: `.venv/bin/pytest tests/test_run_ingest_sources.py tests/test_digest.py -v`

- [ ] **Step 4: Implement persistence helper**

```python
def persist_discovery(conn, result, *, stale_days, reopen_days, dry_run):
    inserted = db.insert_discovered(
        conn, list(result.jobs), stale_days=stale_days, reopen_days=reopen_days
    )
    if dry_run:
        return inserted, ()
    issues = []
    for checkpoint in result.checkpoints:
        try:
            tracker_common.commit_checkpoint(checkpoint)
        except OSError as exc:
            logger.exception("checkpoint commit failed for %s", checkpoint.source)
            issues.append(DiscoveryIssue(
                checkpoint.source, "checkpoint", type(exc).__name__, str(exc)[:500]
            ))
    return inserted, tuple(issues)
```

Serialize combined fetch/checkpoint issues with `dataclasses.asdict`, sorted JSON, and pass it
to `db.finish_run(notes=...)`.

- [ ] **Step 5: Wire main with exact exit semantics**

Use `discovery_result.jobs` for insertion/counters. Commit checkpoints only after
`insert_discovered` returns. Return 1 iff:

```python
all_selected_failed = (
    not args.resolve_only and bool(selected)
    and not discovery_result.succeeded_sources
)
checkpoint_failed = any(issue.stage == "checkpoint" for issue in discovery_issues)
return 1 if all_selected_failed or checkpoint_failed else 0
```

Add `--snapshot-dir`; copy each selected config with this override. Do not mutate the loaded
config object.

- [ ] **Step 6: Render warnings**

Add `_run_warnings(run_row)` to `digest.py`: parse `notes`, render each structured issue, and
fall back to one raw warning line for legacy non-JSON notes. Insert it between resolution tiers
and the per-source table.

- [ ] **Step 7: Verify and commit**

```bash
.venv/bin/pytest tests/test_run_ingest_sources.py tests/test_digest.py \
  tests/test_idempotency.py -v
git add src/run_ingest.py src/digest.py tests/test_run_ingest_sources.py tests/test_digest.py
git commit -m "fix(m9d-0): commit snapshots only after durable insert"
```

Expected: DB failure makes zero checkpoint calls; checkpoint failure is safe and visible.

---

### Task 4: Read-only source-yield and backlog baseline

**Files:**
- Modify: `src/db.py:273-292`
- Create: `scripts/source_baseline.py`, `tests/test_source_baseline.py`

**Interfaces:**
- Produces `db.get_readonly_connection(path)`, `db.source_yield_summary(conn, trailing_runs)`,
  and `db.status_summary(conn)`.
- Produces `build_baseline(conn, trailing_runs, generated_at=None) -> dict`.
- CLI: `python -m scripts.source_baseline --db PATH --runs N --output PATH`.

- [ ] **Step 1: Write failing report tests**

Seed two finished runs with Vansh `(discovered=15, inserted=5, resolved=3, failed=2)` and
Simplify `(8, 2, 2, 0)`, plus DISCOVERED/RESOLVE_FAILED/RESOLVED jobs. Assert:

```python
payload = source_baseline.build_baseline(
    conn, trailing_runs=30, generated_at="2026-07-14T00:00:00+00:00"
)
by_source = {row["source"]: row for row in payload["sources"]}
assert by_source["tracker_vansh"]["credited_unique_rate"] == 5 / 15
assert by_source["tracker_vansh"]["resolution_rate"] == 3 / 5
assert by_source["tracker_simplify"]["credited_unique_rate"] == 2 / 8
assert by_source["tracker_simplify"]["resolution_rate"] == 1.0
assert payload["status_backlog"]["DISCOVERED"]["count"] == 1
assert "source-order attribution" in payload["definitions"]["credited_unique_insertions"]
```

Also assert zero denominators produce `None`, only finished trailing runs participate, the
CLI uses a connection opened with SQLite `mode=ro`, and output leaves
`db_path.read_bytes()` byte-identical.

- [ ] **Step 2: Verify red**

Run: `.venv/bin/pytest tests/test_source_baseline.py -v`

Expected: import failure.

- [ ] **Step 3: Add the read-only connection and SQL helpers in `src/db.py`**

Import `quote` alongside `urlparse`, then add:

```python
def get_readonly_connection(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path).resolve()
    uri = f"file:{quote(str(path), safe='/')}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn
```

This helper must not call `init_db`; a missing DB or pending migration is an explicit error,
not permission for a reporting command to write.

```python
def source_yield_summary(conn, trailing_runs):
    return conn.execute(
        """
        WITH selected_runs AS (
            SELECT id FROM runs WHERE finished_at IS NOT NULL
            ORDER BY id DESC LIMIT ?
        )
        SELECT rs.source, COUNT(*) AS runs_observed,
               SUM(rs.discovered) AS discovered,
               SUM(rs.inserted) AS inserted,
               SUM(rs.resolved) AS resolved,
               SUM(rs.failed) AS failed
        FROM run_sources rs JOIN selected_runs sr ON sr.id = rs.run_id
        GROUP BY rs.source ORDER BY rs.source
        """,
        (trailing_runs,),
    ).fetchall()


def status_summary(conn):
    return conn.execute(
        """
        SELECT status, COUNT(*) AS count,
               MIN(discovered_at) AS oldest_discovered_at
        FROM jobs GROUP BY status ORDER BY status
        """
    ).fetchall()
```

- [ ] **Step 4: Implement `scripts/source_baseline.py`**

The payload contract is:

```python
{
    "schema_version": 1,
    "generated_at": generated_at,
    "trailing_pipeline_runs": trailing_runs,
    "definitions": {
        "credited_unique_insertions": (
            "Rows credited to a source by current source-order attribution after "
            "deduplication; this is not causal or Shapley marginal contribution."
        ),
        "status_backlog": "Current jobs grouped by lifecycle status.",
    },
    "totals": totals,
    "sources": sources,
    "status_backlog": status_backlog,
}
```

Build `sources`, `totals`, and backlog exactly as follows:

```python
def _rate(numerator, denominator):
    return numerator / denominator if denominator else None


def build_baseline(conn, *, trailing_runs, generated_at=None):
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    sources = []
    for row in db.source_yield_summary(conn, trailing_runs):
        discovered = int(row["discovered"] or 0)
        inserted = int(row["inserted"] or 0)
        resolved = int(row["resolved"] or 0)
        failed = int(row["failed"] or 0)
        sources.append({
            "source": row["source"],
            "runs_observed": int(row["runs_observed"]),
            "discovered": discovered,
            "credited_unique_insertions": inserted,
            "credited_unique_rate": _rate(inserted, discovered),
            "resolved": resolved,
            "failed": failed,
            "resolution_rate": _rate(resolved, resolved + failed),
        })
    total_fields = (
        "runs_observed", "discovered", "credited_unique_insertions", "resolved", "failed"
    )
    totals = {field: sum(row[field] for row in sources) for field in total_fields}
    status_backlog = {
        row["status"]: {
            "count": int(row["count"]),
            "oldest_discovered_at": row["oldest_discovered_at"],
        }
        for row in db.status_summary(conn)
    }
    return {
        "schema_version": 1,
        "generated_at": generated_at,
        "trailing_pipeline_runs": trailing_runs,
        "definitions": {
            "credited_unique_insertions": (
                "Rows credited to a source by current source-order attribution after "
                "deduplication; this is not causal or Shapley marginal contribution."
            ),
            "status_backlog": "Current jobs grouped by lifecycle status.",
        },
        "totals": totals,
        "sources": sources,
        "status_backlog": status_backlog,
    }
```

Each source therefore includes `runs_observed`, `discovered`,
`credited_unique_insertions`, `credited_unique_rate`, `resolved`, `failed`, and
`resolution_rate`. Default CLI arguments are `--db data/jobs.db`, `--runs 30`, and
`--output data/metrics/m9d-0-source-baseline.json`; reject `--runs < 1`. `main()` must open
the DB with `db.get_readonly_connection(args.db)`, write sorted/indented JSON plus a final
newline, and contain no SQL.

- [ ] **Step 5: Verify and commit**

```bash
.venv/bin/pytest tests/test_source_baseline.py tests/test_db.py -v
git add src/db.py scripts/source_baseline.py tests/test_source_baseline.py
git commit -m "feat(m9d-0): add source yield and backlog baseline"
```

Expected: report tests pass and DB bytes are unchanged by CLI execution.

---

### Task 5: Regression, isolated live smoke, baseline capture, documentation

**Files:**
- Modify: `docs/ARCHITECTURE.md`, `docs/SELF_HEALING.md`, `docs/ROADMAP.md`,
  `docs/UPGRADE_PLAN.md`, `docs/DECISIONS.md`
- Runtime evidence only: `data/metrics/m9d-0-source-baseline.json` (ignored)

- [ ] **Step 1: Run complete offline verification**

```bash
.venv/bin/pytest -q
git diff --check
```

Expected: at least 391 tests pass; no whitespace errors.

- [ ] **Step 2: Verify scope**

```bash
git diff --name-only ae8f950..HEAD
rg -n "crawlee|apify|mcp" src scripts pyproject.toml
```

Expected: only planned M9D-0 files changed; no new agent/crawler/Apify runtime code or
dependency. Pre-existing Crawl4AI code is unchanged.

- [ ] **Step 3: Run isolated live limit smoke with the user**

```bash
SMOKE_DIR="$(mktemp -d /tmp/job-pipeline-m9d0.XXXXXX)"
.venv/bin/python -m src.run_ingest --source tracker_vansh --discover-only \
  --limit 2 --db "$SMOKE_DIR/jobs.db" --snapshot-dir "$SMOKE_DIR/snapshots"
.venv/bin/python -m src.run_ingest --source tracker_vansh --discover-only \
  --limit 2 --db "$SMOKE_DIR/jobs.db" --snapshot-dir "$SMOKE_DIR/snapshots"
.venv/bin/python -c 'import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); print(c.execute("SELECT COUNT(*) FROM jobs").fetchone()[0])' "$SMOKE_DIR/jobs.db"
```

Expected: first run inserts 2, second inserts the next 2, final count is 4. Production
`data/jobs.db` and `snapshots/` are untouched. If the live source has fewer than four eligible
rows, reproduce the same proof from recorded fixtures; do not weaken the criterion.

- [ ] **Step 4: Capture production baseline read-only**

```bash
.venv/bin/python -m scripts.source_baseline --db data/jobs.db --runs 30 \
  --output data/metrics/m9d-0-source-baseline.json
```

Record in `DECISIONS.md`: timestamp/window, each source metric, DISCOVERED/RESOLVE_FAILED/
RESOLVED counts and oldest dates, plus the source-order-attribution caveat. Do not commit the
ignored live report.

- [ ] **Step 5: Update authoritative docs after evidence exists**

- `ARCHITECTURE.md`: mark checkpoint protocol CURRENT; specify prepare -> DB -> atomic commit,
  `pending_keys`, legacy compatibility, structured issues, and `--snapshot-dir`.
- `SELF_HEALING.md`: distinguish a valid zero from a recorded fetch/checkpoint failure; forbid
  direct production snapshot writes.
- `ROADMAP.md`/`UPGRADE_PLAN.md`: mark only M9D-0 complete; M9D-1..5 remain unimplemented.
- `DECISIONS.md`: record both ordering defects, tests, live smoke, and baseline.

- [ ] **Step 6: Final verification and documentation commit**

```bash
.venv/bin/pytest -q
git diff --check
git status --short
git add docs/ARCHITECTURE.md docs/SELF_HEALING.md docs/ROADMAP.md \
  docs/UPGRADE_PLAN.md docs/DECISIONS.md
git commit -m "docs(m9d-0): record discovery correctness baseline"
```

Expected: full suite passes; only intended files are staged. The user's separate scoring
stress test change stays untouched/uncommitted unless they handled it separately.

## Final acceptance checklist

- [ ] DB insertion failure makes zero checkpoint commit calls.
- [ ] Checkpoint failure leaves old snapshot intact and inserted rows durable, returns nonzero,
  and appears in run notes/digest.
- [ ] Successive limited runs drain deferred keys instead of starving them.
- [ ] Legacy snapshots load without migration.
- [ ] Fetch failure differs from successful zero yield.
- [ ] Partial source failure is nonfatal; all selected sources failing is nonzero with a
  finished run record.
- [ ] Dry run never commits a snapshot.
- [ ] Baseline command is read-only and contains no SQL.
- [ ] Full suite passes with at least 391 tests.
- [ ] Live smoke uses isolated DB/snapshots and proves 2 + 2 = 4.
- [ ] No schema, dependency, crawler, agent, Apify, or new-source work entered M9D-0.
- [ ] M9D-1 through M9D-5 were not started.
