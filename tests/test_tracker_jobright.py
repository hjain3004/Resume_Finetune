from pathlib import Path

from src.discover import tracker_common, tracker_jobright
from src.models import dedup_key

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


def test_prepare_snapshot_first_run_returns_all_without_writing(tmp_path):
    text = (FIXTURES / "jobright_readme.md").read_text()
    jobs = tracker_jobright.parse_readme_table(text)
    prepared = tracker_common.prepare_snapshot_diff(
        jobs, tmp_path, "README.md", tracker_jobright.SOURCE_NAME
    )
    unique_keys = {dedup_key(j.company, j.title, j.location) for j in jobs}
    assert len(prepared.jobs) == len(unique_keys)
    assert not (tmp_path / "tracker_jobright.json").exists()
    tracker_common.commit_checkpoint(prepared.checkpoint)
    assert (tmp_path / "tracker_jobright.json").exists()
