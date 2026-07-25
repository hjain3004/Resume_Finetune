"""M6.13R: the guarded repair of M6.13's terminal-state overwrites."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from scripts.repair_m6_13_overwrites import LEGACY_NOTE, build_restorations, main
from src import db
from src.models import Status


def _conn(path: str | Path = ":memory:"):
    return db.get_connection(path)


def _insert(conn, key, status, *, notes=None, filter_reason=None, score=None):
    conn.execute(
        """
        INSERT INTO jobs (
            dedup_key, company, title, location, url, source, discovered_at,
            status, notes, filter_reason, fit_score
        )
        VALUES (?, 'Acme', 'Software Engineer', 'Remote', ?, 'tracker_vansh',
                '2026-07-01T00:00:00+00:00', ?, ?, ?, ?)
        """,
        (key, f"https://example.com/{key}", status, notes, filter_reason, score),
    )
    conn.commit()
    return conn.execute("SELECT id FROM jobs WHERE dedup_key = ?", (key,)).fetchone()["id"]


def _row(conn, job_id):
    return conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()


@pytest.fixture
def pair(tmp_path):
    """Paths for a live DB and its pre-remediation backup."""
    return tmp_path / "backup.db", tmp_path / "jobs.db"


def _clone_to_live(backup_path: Path, live_path: Path):
    """The live DB starts as an exact copy of the backup, as in production."""
    shutil.copyfile(backup_path, live_path)
    return _conn(live_path)


def _overwrite(live, job_id, prior_notes=None):
    """Reproduce what M6.13 did: CLOSED + appended note, nothing else."""
    notes = f"{prior_notes}; {LEGACY_NOTE}" if prior_notes else LEGACY_NOTE
    live.execute(
        "UPDATE jobs SET status = ?, notes = ? WHERE id = ?", (Status.CLOSED, notes, job_id)
    )
    live.commit()


# --- preview -----------------------------------------------------------------


def test_proposes_only_filtered_out_rows_overwritten_by_m6_13(pair):
    backup_path, live_path = pair
    backup = _conn(backup_path)
    repairable = _insert(backup, "filtered", "FILTERED_OUT", filter_reason="eligibility:country")
    from_resolved = _insert(backup, "resolved", "RESOLVED")
    untouched = _insert(backup, "kept", "FILTERED_OUT", filter_reason="location")
    backup.close()

    live = _clone_to_live(backup_path, live_path)
    _overwrite(live, repairable)
    _overwrite(live, from_resolved)

    rows = build_restorations(live, db.get_readonly_connection(backup_path))

    assert [r.job_id for r in rows] == [repairable]
    assert rows[0].restored_status == "FILTERED_OUT"
    assert rows[0].expected_status == "CLOSED"
    assert _row(live, untouched)["status"] == "FILTERED_OUT"


def test_does_not_propose_a_closed_row_that_m6_13_did_not_touch(pair):
    backup_path, live_path = pair
    backup = _conn(backup_path)
    job_id = _insert(backup, "filtered", "FILTERED_OUT")
    backup.close()

    live = _clone_to_live(backup_path, live_path)
    live.execute(
        "UPDATE jobs SET status = ?, notes = ? WHERE id = ?",
        (Status.CLOSED, "M6.8: liveness recheck returned 410", job_id),
    )
    live.commit()

    assert build_restorations(live, db.get_readonly_connection(backup_path)) == ()


def test_does_not_propose_a_row_whose_other_notes_also_changed(pair):
    """Stripping the M6.13 note must reproduce the backup exactly."""
    backup_path, live_path = pair
    backup = _conn(backup_path)
    job_id = _insert(backup, "filtered", "FILTERED_OUT", notes="resolver: tier-2")
    backup.close()

    live = _clone_to_live(backup_path, live_path)
    live.execute(
        "UPDATE jobs SET status = ?, notes = ? WHERE id = ?",
        (Status.CLOSED, f"resolver: tier-2; later audit note; {LEGACY_NOTE}", job_id),
    )
    live.commit()

    assert build_restorations(live, db.get_readonly_connection(backup_path)) == ()


# --- apply --------------------------------------------------------------------


def test_apply_restores_status_and_strips_only_the_m6_13_note(pair):
    backup_path, live_path = pair
    backup = _conn(backup_path)
    bare = _insert(backup, "bare", "FILTERED_OUT", filter_reason="eligibility:country")
    with_notes = _insert(
        backup, "noted", "FILTERED_OUT", notes="resolver: tier-2", filter_reason="location"
    )
    backup.close()

    live = _clone_to_live(backup_path, live_path)
    _overwrite(live, bare)
    _overwrite(live, with_notes, prior_notes="resolver: tier-2")
    rows = build_restorations(live, db.get_readonly_connection(backup_path))

    changed = db.apply_terminal_state_restorations(live, rows)

    assert changed == 2
    assert _row(live, bare)["status"] == "FILTERED_OUT"
    assert _row(live, bare)["notes"] is None
    assert _row(live, bare)["filter_reason"] == "eligibility:country"
    assert _row(live, with_notes)["notes"] == "resolver: tier-2"
    assert _row(live, with_notes)["filter_reason"] == "location"


def test_apply_does_not_invent_scoring_fields(pair):
    backup_path, live_path = pair
    backup = _conn(backup_path)
    job_id = _insert(backup, "filtered", "FILTERED_OUT")
    backup.close()

    live = _clone_to_live(backup_path, live_path)
    _overwrite(live, job_id)
    rows = build_restorations(live, db.get_readonly_connection(backup_path))

    db.apply_terminal_state_restorations(live, rows)

    assert _row(live, job_id)["fit_score"] is None
    assert _row(live, job_id)["fit_rationale"] is None


def test_apply_is_idempotent(pair):
    backup_path, live_path = pair
    backup = _conn(backup_path)
    job_id = _insert(backup, "filtered", "FILTERED_OUT", notes="resolver: tier-2")
    backup.close()

    live = _clone_to_live(backup_path, live_path)
    _overwrite(live, job_id, prior_notes="resolver: tier-2")
    rows = build_restorations(live, db.get_readonly_connection(backup_path))

    first = db.apply_terminal_state_restorations(live, rows)
    second = db.apply_terminal_state_restorations(live, rows)

    assert (first, second) == (1, 0)
    assert _row(live, job_id)["notes"] == "resolver: tier-2"


def test_apply_rolls_back_when_a_row_drifted_after_the_preview(pair):
    backup_path, live_path = pair
    backup = _conn(backup_path)
    stable = _insert(backup, "stable", "FILTERED_OUT")
    drifted = _insert(backup, "drifted", "FILTERED_OUT")
    backup.close()

    live = _clone_to_live(backup_path, live_path)
    _overwrite(live, stable)
    _overwrite(live, drifted)
    rows = build_restorations(live, db.get_readonly_connection(backup_path))
    live.execute("UPDATE jobs SET status = ? WHERE id = ?", (Status.APPLIED, drifted))
    live.commit()

    with pytest.raises(db.StalePreviewError):
        db.apply_terminal_state_restorations(live, rows)

    assert _row(live, stable)["status"] == "CLOSED"
    assert _row(live, drifted)["status"] == "APPLIED"


# --- CLI ----------------------------------------------------------------------


def test_cli_preview_writes_auditable_artifact_and_does_not_mutate(pair):
    backup_path, live_path = pair
    out = live_path.parent / "preview.json"
    backup = _conn(backup_path)
    job_id = _insert(backup, "filtered", "FILTERED_OUT", filter_reason="eligibility:country")
    backup.close()

    live = _clone_to_live(backup_path, live_path)
    _overwrite(live, job_id)
    live.close()

    argv = ["--db", str(live_path), "--from-backup", str(backup_path), "--json", str(out)]
    assert main(argv) == 0

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["count"] == 1
    assert payload["counts_by_restored_status"] == {"FILTERED_OUT": 1}
    (row,) = payload["rows"]
    assert row["job_id"] == job_id
    assert row["expected_status"] == "CLOSED"
    assert row["restored_status"] == "FILTERED_OUT"
    assert row["filter_reason"] == "eligibility:country"

    check = db.get_readonly_connection(live_path)
    assert check.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()[0] == "CLOSED"


def test_cli_apply_requires_confirm_and_backup(pair):
    backup_path, live_path = pair
    _conn(backup_path).close()
    _conn(live_path).close()

    argv = ["--db", str(live_path), "--from-backup", str(backup_path), "--apply"]
    assert main(argv) == 2
    assert main([*argv, "--confirm", "APPLY"]) == 2


def test_cli_apply_restores_and_writes_a_new_backup(pair):
    backup_path, live_path = pair
    new_backup = live_path.parent / "pre_repair.db"
    backup = _conn(backup_path)
    job_id = _insert(backup, "filtered", "FILTERED_OUT", filter_reason="location")
    backup.close()

    live = _clone_to_live(backup_path, live_path)
    _overwrite(live, job_id)
    live.close()

    exit_code = main(
        [
            "--db", str(live_path),
            "--from-backup", str(backup_path),
            "--apply", "--confirm", "APPLY",
            "--backup", str(new_backup),
        ]
    )

    assert exit_code == 0
    assert new_backup.exists()
    check = db.get_readonly_connection(live_path)
    row = check.execute(
        "SELECT status, notes, filter_reason FROM jobs WHERE id = ?", (job_id,)
    ).fetchone()
    assert row["status"] == "FILTERED_OUT"
    assert row["notes"] is None
    assert row["filter_reason"] == "location"
