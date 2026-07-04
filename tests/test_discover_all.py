from types import SimpleNamespace

from src import db
from src.discover import discover_all
from src.models import DiscoveredJob


def _fake_adapter(jobs=None, *, raises=False):
    def discover(config):
        if raises:
            raise RuntimeError("boom")
        return list(jobs or [])

    return SimpleNamespace(discover=discover)


def test_adapter_exception_does_not_prevent_other_adapters(monkeypatch):
    good_job = DiscoveredJob("Acme", "SWE", "Remote", "https://acme.example/1", "source_a", None)
    monkeypatch.setattr(
        "src.discover.ADAPTERS",
        {
            "source_a": _fake_adapter([good_job]),
            "source_b": _fake_adapter(raises=True),
        },
    )
    jobs = discover_all({"source_a": {"enabled": True}, "source_b": {"enabled": True}})
    assert jobs == [good_job]


def test_disabled_and_unregistered_sources_are_skipped(monkeypatch):
    monkeypatch.setattr("src.discover.ADAPTERS", {"source_a": _fake_adapter([])})
    jobs = discover_all(
        {"source_a": {"enabled": False}, "source_unknown": {"enabled": True}}
    )
    assert jobs == []


def test_limit_caps_jobs_per_source(monkeypatch):
    jobs = [
        DiscoveredJob("Acme", f"SWE {i}", None, f"https://acme.example/{i}", "source_a", None)
        for i in range(5)
    ]
    monkeypatch.setattr("src.discover.ADAPTERS", {"source_a": _fake_adapter(jobs)})
    result = discover_all({"source_a": {"enabled": True}}, limit=2)
    assert len(result) == 2


def test_cross_source_dedup_upgrades_to_higher_priority_source(monkeypatch):
    """Same job discovered via two trackers -> one DB row, source upgraded
    per SOURCE_PRIORITY (ARCHITECTURE §4.3)."""
    low_priority = DiscoveredJob(
        "Acme", "Software Engineer", "Remote", "https://jobright.example/1", "tracker_jobright", None
    )
    high_priority = DiscoveredJob(
        "Acme", "Software Engineer", "Remote", "https://simplify.example/1", "tracker_simplify", None
    )
    monkeypatch.setattr(
        "src.discover.ADAPTERS",
        {
            "tracker_jobright": _fake_adapter([low_priority]),
            "tracker_simplify": _fake_adapter([high_priority]),
        },
    )
    jobs = discover_all(
        {"tracker_jobright": {"enabled": True}, "tracker_simplify": {"enabled": True}}
    )

    conn = db.get_connection(":memory:")
    new_count = db.insert_discovered(conn, jobs)

    rows = conn.execute("SELECT * FROM jobs").fetchall()
    assert new_count == 1
    assert len(rows) == 1
    assert rows[0]["source"] == "tracker_simplify"
    assert rows[0]["url"] == "https://simplify.example/1"
