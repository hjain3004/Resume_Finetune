import json
from pathlib import Path

from src.discover import tracker_common, tracker_simplify

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_listings_json_row_count_and_filters_inactive():
    entries = json.loads((FIXTURES / "simplify_listings.json").read_text())
    jobs = tracker_simplify.parse_listings_json(entries)
    assert len(jobs) > 0
    assert len(jobs) < len(entries)
    assert all(j.company and j.title and j.url for j in jobs)
    assert all(j.source == "tracker_simplify" for j in jobs)


def test_parse_listings_json_spot_check():
    entries = json.loads((FIXTURES / "simplify_listings.json").read_text())
    jobs = tracker_simplify.parse_listings_json(entries)
    newsbreak = next(j for j in jobs if j.company == "NewsBreak")
    assert "ML Infra" in newsbreak.title
    assert newsbreak.location == "Mountain View, CA"


def test_prepare_snapshot_first_run_returns_all_without_writing(tmp_path):
    entries = json.loads((FIXTURES / "simplify_listings.json").read_text())
    jobs = tracker_simplify.parse_listings_json(entries)
    prepared = tracker_common.prepare_snapshot_diff(
        jobs, tmp_path, "listings.json", tracker_simplify.SOURCE_NAME
    )
    assert len(prepared.jobs) == len(jobs)
    assert not (tmp_path / "tracker_simplify.json").exists()


def test_prepare_snapshot_second_run_only_returns_new_rows_after_commit(tmp_path):
    base_entries = json.loads((FIXTURES / "simplify_listings.json").read_text())
    plus2_entries = json.loads((FIXTURES / "simplify_listings_plus2.json").read_text())

    base_jobs = tracker_simplify.parse_listings_json(base_entries)
    prepared = tracker_common.prepare_snapshot_diff(
        base_jobs, tmp_path, "listings.json", tracker_simplify.SOURCE_NAME
    )
    tracker_common.commit_checkpoint(prepared.checkpoint)

    plus2_jobs = tracker_simplify.parse_listings_json(plus2_entries)
    new_jobs = tracker_common.prepare_snapshot_diff(
        plus2_jobs, tmp_path, "listings.json", tracker_simplify.SOURCE_NAME
    ).jobs

    assert len(new_jobs) == 2
    assert {j.company for j in new_jobs} == {"Example Corp", "Example Corp Two"}
