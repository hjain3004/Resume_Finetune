from types import SimpleNamespace

from src import db
from src.discover import discover_all
from src.discover.base import AdapterDiscovery, DiscoveryIssue, PendingCheckpoint
from src.models import DiscoveredJob


def _fake_adapter(jobs=None, *, raises=False):
    def discover(config):
        if raises:
            raise RuntimeError("boom")
        return AdapterDiscovery("source_a", tuple(jobs or ()), None)

    return SimpleNamespace(discover=discover)


def test_failure_is_preserved_and_other_source_succeeds():
    good_job = DiscoveredJob("Acme", "SWE", "Remote", "https://acme.example/1", "source_a", None)
    result = discover_all(
        {"good": {"enabled": True}, "bad": {"enabled": True}},
        adapters={
            "good": _fake_adapter([good_job]),
            "bad": _fake_adapter(raises=True),
        },
    )
    assert result.jobs == (good_job,)
    assert result.succeeded_sources == ("good",)
    assert result.issues == (
        DiscoveryIssue("bad", "fetch", "RuntimeError", "boom"),
    )


def test_disabled_and_unregistered_sources_are_skipped():
    result = discover_all(
        {"source_a": {"enabled": False}, "source_unknown": {"enabled": True}},
        adapters={"source_a": _fake_adapter([])},
    )
    assert result.jobs == ()
    assert result.checkpoints == ()
    assert result.succeeded_sources == ()
    assert result.issues == ()


def test_limit_is_passed_to_adapter():
    jobs = [
        DiscoveredJob("Acme", f"SWE {i}", None, f"https://acme.example/{i}", "source_a", None)
        for i in range(5)
    ]

    def discover(config):
        assert config["limit"] == 2
        return AdapterDiscovery("good", tuple(jobs[: config["limit"]]), None)

    result = discover_all(
        {"good": {"enabled": True}}, limit=2, adapters={"good": SimpleNamespace(discover=discover)}
    )
    assert len(result.jobs) == 2


def test_checkpoint_is_returned_but_not_written(tmp_path):
    checkpoint = PendingCheckpoint(
        "good",
        tmp_path / "good.json",
        "listings.json",
        frozenset({"a"}),
        frozenset(),
    )

    def discover(config):
        return AdapterDiscovery("good", (), checkpoint)

    result = discover_all(
        {"good": {"enabled": True}}, adapters={"good": SimpleNamespace(discover=discover)}
    )
    assert result.checkpoints == (checkpoint,)
    assert not result.checkpoints[0].path.exists()


def test_cross_source_dedup_upgrades_to_higher_priority_source():
    """Same job discovered via two trackers -> one DB row, source upgraded
    per SOURCE_PRIORITY (ARCHITECTURE §4.3)."""
    low_priority = DiscoveredJob(
        "Acme", "Software Engineer", "Remote", "https://jobright.example/1", "tracker_jobright", None
    )
    high_priority = DiscoveredJob(
        "Acme", "Software Engineer", "Remote", "https://simplify.example/1", "tracker_simplify", None
    )
    jobs = discover_all(
        {"tracker_jobright": {"enabled": True}, "tracker_simplify": {"enabled": True}},
        adapters={
            "tracker_jobright": _fake_adapter([low_priority]),
            "tracker_simplify": _fake_adapter([high_priority]),
        },
    )

    conn = db.get_connection(":memory:")
    new_count = db.insert_discovered(conn, list(jobs.jobs))

    rows = conn.execute("SELECT * FROM jobs").fetchall()
    assert sum(new_count.values()) == 1
    assert len(rows) == 1
    assert rows[0]["source"] == "tracker_simplify"
    assert rows[0]["url"] == "https://simplify.example/1"
