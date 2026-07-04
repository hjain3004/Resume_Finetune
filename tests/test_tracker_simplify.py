import json
from pathlib import Path

from src.discover import tracker_simplify

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


def test_snapshot_diff_first_run_returns_all(tmp_path):
    entries = json.loads((FIXTURES / "simplify_listings.json").read_text())
    jobs = tracker_simplify.parse_listings_json(entries)
    new_jobs = tracker_simplify.diff_new_jobs(jobs, tmp_path, "listings.json")
    assert len(new_jobs) == len(jobs)


def test_snapshot_diff_second_run_only_returns_new_rows(tmp_path):
    base_entries = json.loads((FIXTURES / "simplify_listings.json").read_text())
    plus2_entries = json.loads((FIXTURES / "simplify_listings_plus2.json").read_text())

    base_jobs = tracker_simplify.parse_listings_json(base_entries)
    tracker_simplify.diff_new_jobs(base_jobs, tmp_path, "listings.json")

    plus2_jobs = tracker_simplify.parse_listings_json(plus2_entries)
    new_jobs = tracker_simplify.diff_new_jobs(plus2_jobs, tmp_path, "listings.json")

    assert len(new_jobs) == 2
    assert {j.company for j in new_jobs} == {"Example Corp", "Example Corp Two"}
