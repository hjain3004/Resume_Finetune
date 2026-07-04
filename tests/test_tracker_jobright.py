from pathlib import Path

from src.discover import tracker_jobright

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_readme_table_finds_rows():
    text = (FIXTURES / "jobright_readme.md").read_text()
    jobs = tracker_jobright.parse_readme_table(text)
    assert len(jobs) > 0
    assert all(j.source == "tracker_jobright" for j in jobs)


def test_parse_readme_table_extracts_link_from_title_cell():
    text = (FIXTURES / "jobright_readme.md").read_text()
    jobs = tracker_jobright.parse_readme_table(text)
    by_company = {j.company: j for j in jobs}

    assert "Carollo Engineers" in by_company
    carollo = by_company["Carollo Engineers"]
    assert carollo.title == "Infrastructure Engineer (All levels Entry through Senior)"
    assert carollo.url.startswith("https://jobright.ai/jobs/info/")
    assert carollo.location == "Walnut Creek, CA, US"


def test_snapshot_diff_first_run_returns_all(tmp_path):
    text = (FIXTURES / "jobright_readme.md").read_text()
    jobs = tracker_jobright.parse_readme_table(text)
    new_jobs = tracker_jobright.diff_new_jobs(jobs, tmp_path, "README.md")
    assert len(new_jobs) == len(jobs)
