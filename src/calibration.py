"""Calibration Contract v2 primitives.

Pure artifact/model helpers live here. CLI wrappers and database SQL stay
outside this module per the project architecture.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any
import hashlib

VALID_CALLS = frozenset({"APPLY", "MAYBE", "SKIP"})
CONTRACT_VERSION = 2
DEFAULT_ROUND_LIMIT = 12

_BATCH_FIELDS = {
    "id",
    "row_ids",
    "company",
    "title",
    "locations",
    "flags",
    "jd_quality",
    "jd_text",
}
_JD_QUALITIES = frozenset({"ats", "aggregator"})


class CalibrationContractError(ValueError):
    """Raised when a calibration artifact violates the written contract."""


class CalibrationStage(str, Enum):
    INTEREST = "interest"
    FIT = "fit"
    LEGACY_INTEREST = "legacy_interest"


@dataclass(frozen=True)
class BatchJob:
    job_id: int
    row_ids: tuple[int, ...]
    company: str
    title: str
    locations: tuple[str, ...]
    flags: tuple[str, ...]
    jd_quality: str
    jd_text: str


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: str | Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def _require_nonempty_string(value: object, *, field: str, index: int) -> str:
    if not isinstance(value, str) or not value:
        raise CalibrationContractError(f"batch object {index}: {field} must be a non-empty string")
    return value


def _require_string_list(value: object, *, field: str, index: int) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise CalibrationContractError(f"batch object {index}: {field} must be a list of strings")
    return tuple(value)


def _parse_batch_job(value: object, *, index: int) -> BatchJob:
    if not isinstance(value, dict):
        raise CalibrationContractError(f"batch object {index}: object must be a mapping")
    keys = set(value)
    missing = _BATCH_FIELDS - keys
    extra = keys - _BATCH_FIELDS
    if missing:
        raise CalibrationContractError(f"batch object {index}: missing fields {sorted(missing)}")
    if extra:
        raise CalibrationContractError(f"batch object {index}: extra fields {sorted(extra)}")

    job_id = value["id"]
    if not isinstance(job_id, int) or isinstance(job_id, bool) or job_id <= 0:
        raise CalibrationContractError(f"batch object {index}: id must be a positive integer")

    row_ids_value = value["row_ids"]
    if (
        not isinstance(row_ids_value, list)
        or not row_ids_value
        or any(not isinstance(row_id, int) or isinstance(row_id, bool) or row_id <= 0 for row_id in row_ids_value)
    ):
        raise CalibrationContractError(f"batch object {index}: row_ids must be non-empty positive integers")
    row_ids = tuple(row_ids_value)
    if len(set(row_ids)) != len(row_ids):
        raise CalibrationContractError(f"batch object {index}: duplicate row_ids are not allowed")
    if job_id not in row_ids:
        raise CalibrationContractError(f"batch object {index}: row_ids must contain canonical id {job_id}")

    jd_quality = value["jd_quality"]
    if jd_quality not in _JD_QUALITIES:
        raise CalibrationContractError(f"batch object {index}: jd_quality must be ats or aggregator")

    return BatchJob(
        job_id=job_id,
        row_ids=row_ids,
        company=_require_nonempty_string(value["company"], field="company", index=index),
        title=_require_nonempty_string(value["title"], field="title", index=index),
        locations=_require_string_list(value["locations"], field="locations", index=index),
        flags=_require_string_list(value["flags"], field="flags", index=index),
        jd_quality=jd_quality,
        jd_text=_require_nonempty_string(value["jd_text"], field="jd_text", index=index),
    )


def load_batch(path: str | Path) -> tuple[BatchJob, ...]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CalibrationContractError(f"{path}: invalid JSON: {exc}") from exc
    if not isinstance(raw, list):
        raise CalibrationContractError(f"{path}: JSON root must be a list")

    jobs = tuple(_parse_batch_job(obj, index=index) for index, obj in enumerate(raw, start=1))
    canonical_ids: set[int] = set()
    all_row_ids: set[int] = set()
    for job in jobs:
        if job.job_id in canonical_ids:
            raise CalibrationContractError(f"{path}: duplicate canonical id {job.job_id}")
        canonical_ids.add(job.job_id)
        overlap = all_row_ids & set(job.row_ids)
        if overlap:
            raise CalibrationContractError(f"{path}: row_ids overlap across groups: {sorted(overlap)}")
        all_row_ids.update(job.row_ids)
    return jobs


def select_round_jobs(jobs: tuple[BatchJob, ...], limit: int = DEFAULT_ROUND_LIMIT) -> tuple[BatchJob, ...]:
    if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
        raise CalibrationContractError(f"round limit must be a positive integer; got {limit!r}")
    available = len(jobs)
    if limit > available:
        raise CalibrationContractError(f"round limit {limit} exceeds available jobs {available}")
    return jobs[:limit]


def batch_jobs_to_json(jobs: tuple[BatchJob, ...]) -> str:
    objects = [
        {
            "id": job.job_id,
            "row_ids": list(job.row_ids),
            "company": job.company,
            "title": job.title,
            "locations": list(job.locations),
            "flags": list(job.flags),
            "jd_quality": job.jd_quality,
            "jd_text": job.jd_text,
        }
        for job in jobs
    ]
    return json.dumps(objects, indent=2) + "\n"


def atomic_write_text(path: str | Path, text: str) -> None:
    destination = Path(path)
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            tmp_name = tmp.name
            tmp.write(text)
            tmp.flush()
            os.fsync(tmp.fileno())
        if destination.exists():
            raise FileExistsError(destination)
        os.replace(tmp_name, destination)
        tmp_name = None
    finally:
        if tmp_name is not None:
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass
