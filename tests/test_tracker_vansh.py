import json
from pathlib import Path

from src.discover import tracker_vansh

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_readme_table_finds_rows():
    text = (FIXTURES / "vansh_readme.md").read_text()
    jobs = tracker_vansh.parse_readme_table(text)
    assert len(jobs) > 0


def test_parse_readme_table_spot_check_known_rows():
    text = (FIXTURES / "vansh_readme.md").read_text()
    jobs = tracker_vansh.parse_readme_table(text)
    by_company = {(j.company, j.title): j for j in jobs}

    assert ("Uber Technologies, Inc.", "Software Engineer I, Masters") in by_company
    uber_job = by_company[("Uber Technologies, Inc.", "Software Engineer I, Masters")]
    assert uber_job.url.startswith("https://www.uber.com/global/en/careers/")

    assert ("Remitly", "Software Development Engineer 1, Pricing Platform") in by_company
    remitly_job = by_company[("Remitly", "Software Development Engineer 1, Pricing Platform")]
    assert remitly_job.location == "Seattle, WA"

    assert ("Ivo", "Software Engineer, Frontend") in by_company


def test_parse_readme_table_skips_closed_rows():
    text = (FIXTURES / "vansh_readme.md").read_text()
    jobs = tracker_vansh.parse_readme_table(text)
    assert not any(j.company == "Microsoft" and j.title == "Site Reliability Engineer" for j in jobs)


def test_parse_listings_json_row_count_and_filters_inactive():
    entries = json.loads((FIXTURES / "vansh_listings.json").read_text())
    jobs = tracker_vansh.parse_listings_json(entries)
    assert len(jobs) > 0
    assert len(jobs) < len(entries)  # inactive rows dropped
    assert all(j.company and j.title and j.url for j in jobs)


def test_parse_listings_json_spot_check():
    entries = json.loads((FIXTURES / "vansh_listings.json").read_text())
    jobs = tracker_vansh.parse_listings_json(entries)
    qualcomm = next(j for j in jobs if j.company == "Qualcomm")
    assert qualcomm.title == "Embedded DSP Software Engineer"
    assert qualcomm.location == "San Diego, CA"
    assert qualcomm.date_posted == "2025-03-31"


def test_snapshot_diff_first_run_returns_all(tmp_path):
    entries = json.loads((FIXTURES / "vansh_listings.json").read_text())
    jobs = tracker_vansh.parse_listings_json(entries)
    new_jobs = tracker_vansh.diff_new_jobs(jobs, tmp_path, "listings.json")
    assert len(new_jobs) == len(jobs)


def test_snapshot_diff_second_run_only_returns_new_rows(tmp_path):
    base_entries = json.loads((FIXTURES / "vansh_listings.json").read_text())
    plus2_entries = json.loads((FIXTURES / "vansh_listings_plus2.json").read_text())

    base_jobs = tracker_vansh.parse_listings_json(base_entries)
    tracker_vansh.diff_new_jobs(base_jobs, tmp_path, "listings.json")

    plus2_jobs = tracker_vansh.parse_listings_json(plus2_entries)
    new_jobs = tracker_vansh.diff_new_jobs(plus2_jobs, tmp_path, "listings.json")

    assert len(new_jobs) == 2
    assert {j.company for j in new_jobs} == {"Example Corp", "Example Corp Two"}


def test_snapshot_diff_writes_snapshot_file(tmp_path):
    entries = json.loads((FIXTURES / "vansh_listings.json").read_text())
    jobs = tracker_vansh.parse_listings_json(entries)
    tracker_vansh.diff_new_jobs(jobs, tmp_path, "listings.json")
    snapshot_file = tmp_path / "tracker_vansh.json"
    assert snapshot_file.exists()
    data = json.loads(snapshot_file.read_text())
    assert data["source_path"] == "listings.json"
    assert len(data["keys"]) == len(jobs)
