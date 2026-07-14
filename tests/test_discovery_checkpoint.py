import json
import os

import pytest

from src.discover import tracker_common
from src.models import DiscoveredJob, dedup_key


def job(n):
    return DiscoveredJob(
        f"Company {n}",
        f"SWE {n}",
        "Remote",
        f"https://example.com/{n}",
        "tracker_test",
        None,
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
    assert (
        tracker_common.prepare_snapshot_diff(
            items, tmp_path, "listings.json", "tracker_test", limit=1
        ).jobs
        == ()
    )


def test_prepare_deduplicates_one_fetch(tmp_path):
    assert (
        tracker_common.prepare_snapshot_diff(
            [job(1), job(1)], tmp_path, "listings.json", "tracker_test"
        ).jobs
        == (job(1),)
    )


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
