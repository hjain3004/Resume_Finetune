import json

import pytest

from src.calibration import (
    BatchJob,
    CalibrationContractError,
    atomic_write_text,
    batch_jobs_to_json,
    load_batch,
    select_round_jobs,
    sha256_bytes,
)


def _batch_obj(job_id: int, *, row_ids: list[int] | None = None, **overrides: object) -> dict[str, object]:
    obj: dict[str, object] = {
        "id": job_id,
        "row_ids": row_ids if row_ids is not None else [job_id],
        "company": f"Company {job_id}",
        "title": f"Software Engineer {job_id}",
        "locations": ["New York, NY", "Remote US"],
        "flags": ["authorization_ambiguous"] if job_id % 2 == 0 else [],
        "jd_quality": "ats",
        "jd_text": f"Complete JD text for job {job_id}",
    }
    obj.update(overrides)
    return obj


def _write_batch(tmp_path, objects: list[dict[str, object]]):
    path = tmp_path / "batch.json"
    path.write_text(json.dumps(objects), encoding="utf-8")
    return path


def _valid_jobs(count: int = 14) -> tuple[BatchJob, ...]:
    return tuple(
        BatchJob(
            job_id=i,
            row_ids=(i,),
            company=f"Company {i}",
            title=f"Software Engineer {i}",
            locations=("New York, NY", "Remote US"),
            flags=("authorization_ambiguous",) if i % 2 == 0 else (),
            jd_quality="ats",
            jd_text=f"Complete JD text for job {i}",
        )
        for i in range(1, count + 1)
    )


def test_select_round_jobs_defaults_to_first_12_and_supports_explicit_limit():
    jobs = _valid_jobs(14)

    assert [job.job_id for job in select_round_jobs(jobs)] == list(range(1, 13))
    assert [job.job_id for job in select_round_jobs(jobs, limit=2)] == [1, 2]


@pytest.mark.parametrize("limit", [0, -1, 1.5, "2"])
def test_select_round_jobs_rejects_invalid_limits(limit):
    with pytest.raises(CalibrationContractError, match="limit"):
        select_round_jobs(_valid_jobs(14), limit=limit)  # type: ignore[arg-type]


def test_select_round_jobs_rejects_limit_greater_than_available():
    with pytest.raises(CalibrationContractError, match="available.*2"):
        select_round_jobs(_valid_jobs(2), limit=3)


def test_load_batch_preserves_source_order_and_types(tmp_path):
    path = _write_batch(tmp_path, [_batch_obj(3), _batch_obj(1), _batch_obj(2)])

    jobs = load_batch(path)

    assert [job.job_id for job in jobs] == [3, 1, 2]
    assert jobs[0] == BatchJob(
        job_id=3,
        row_ids=(3,),
        company="Company 3",
        title="Software Engineer 3",
        locations=("New York, NY", "Remote US"),
        flags=(),
        jd_quality="ats",
        jd_text="Complete JD text for job 3",
    )


@pytest.mark.parametrize(
    ("objects", "message"),
    [
        ({"id": 1}, "JSON root"),
        ([_batch_obj(1) | {"unexpected": True}], "extra"),
        ([{k: v for k, v in _batch_obj(1).items() if k != "title"}], "missing"),
        ([_batch_obj(1, id="1")], "id"),
        ([_batch_obj(1, row_ids=[])], "row_ids"),
        ([_batch_obj(1, row_ids=[1, 1])], "duplicate"),
        ([_batch_obj(1, row_ids=[2])], "contain canonical"),
        ([_batch_obj(1), _batch_obj(1)], "duplicate canonical"),
        ([_batch_obj(1, row_ids=[1, 2]), _batch_obj(3, row_ids=[2, 3])], "overlap"),
        ([_batch_obj(1, company="")], "company"),
        ([_batch_obj(1, locations=["Remote", 7])], "locations"),
        ([_batch_obj(1, flags=["ok", 7])], "flags"),
        ([_batch_obj(1, jd_quality="summary")], "jd_quality"),
        ([_batch_obj(1, jd_text=7)], "jd_text"),
    ],
)
def test_load_batch_rejects_invalid_shapes(tmp_path, objects, message):
    path = _write_batch(tmp_path, objects if isinstance(objects, list) else objects)

    with pytest.raises(CalibrationContractError, match=message):
        load_batch(path)


def test_batch_jobs_to_json_is_stable_and_hashable():
    jobs = _valid_jobs(2)

    serialized = batch_jobs_to_json(jobs)

    assert serialized.endswith("\n")
    assert json.loads(serialized) == [
        {
            "id": 1,
            "row_ids": [1],
            "company": "Company 1",
            "title": "Software Engineer 1",
            "locations": ["New York, NY", "Remote US"],
            "flags": [],
            "jd_quality": "ats",
            "jd_text": "Complete JD text for job 1",
        },
        {
            "id": 2,
            "row_ids": [2],
            "company": "Company 2",
            "title": "Software Engineer 2",
            "locations": ["New York, NY", "Remote US"],
            "flags": ["authorization_ambiguous"],
            "jd_quality": "ats",
            "jd_text": "Complete JD text for job 2",
        },
    ]
    assert sha256_bytes(serialized.encode("utf-8")) == sha256_bytes(batch_jobs_to_json(jobs).encode("utf-8"))


def test_atomic_write_text_refuses_existing_destination_and_keeps_bytes(tmp_path):
    path = tmp_path / "artifact.md"
    path.write_text("original", encoding="utf-8")

    with pytest.raises(FileExistsError):
        atomic_write_text(path, "replacement")

    assert path.read_text(encoding="utf-8") == "original"


def test_atomic_write_text_creates_new_file(tmp_path):
    path = tmp_path / "artifact.md"

    atomic_write_text(path, "new text")

    assert path.read_text(encoding="utf-8") == "new text"
