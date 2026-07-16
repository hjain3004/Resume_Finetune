"""Calibration Contract v2 primitives.

Pure artifact/model helpers live here. CLI wrappers and database SQL stay
outside this module per the project architecture.
"""

from __future__ import annotations

import json
import os
import tempfile
import html
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
import hashlib

import yaml

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


@dataclass(frozen=True)
class RoundMetadata:
    contract_version: int
    stage: CalibrationStage
    round_name: str
    batch_path: Path
    batch_sha256: str
    canonical_job_count: int
    created_at: str
    interest_path: Path | None = None
    interest_sha256: str | None = None


@dataclass(frozen=True)
class CalibrationLabel:
    job: BatchJob
    interest_call: str | None
    fit_call: str | None
    notes: str


@dataclass(frozen=True)
class LegacyMetadata:
    contract_version: int
    stage: CalibrationStage
    source_path: Path


@dataclass(frozen=True)
class CalibrationWorksheet:
    metadata: RoundMetadata | LegacyMetadata
    labels: tuple[CalibrationLabel, ...]


@dataclass(frozen=True)
class FullJD:
    job_id: int
    company: str
    title: str
    jd_text: str


_REPO_ROOT = Path(__file__).resolve().parents[1]
_INTEREST_COLUMNS = ("id", "row_ids", "company", "title", "locations", "flags", "jd_quality", "interest_call", "notes")
_FIT_COLUMNS = (
    "id",
    "row_ids",
    "company",
    "title",
    "locations",
    "flags",
    "jd_quality",
    "interest_call",
    "fit_call",
    "notes",
)
_JD_MARKER_PREFIX = "<!-- CALIBRATION_JD_"
_ESCAPED_JD_MARKER_PREFIX = "&lt;!-- CALIBRATION_JD_"


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


def encode_cell(value: str) -> str:
    return value.replace("&", "&amp;").replace("|", "&#124;").replace("\n", "<br>")


def decode_cell(value: str) -> str:
    return html.unescape(value.replace("<br>", "\n"))


def _path_for_metadata(path: Path) -> str:
    try:
        return path.resolve().relative_to(_REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def _resolve_artifact_path(path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return _REPO_ROOT / candidate


def _validate_sha256(value: object, *, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise CalibrationContractError(f"{field} must be a 64-character lowercase sha256")
    return value


def _validate_created_at(value: object) -> str:
    if not isinstance(value, str):
        raise CalibrationContractError("created_at must be a UTC ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise CalibrationContractError("created_at must be a UTC ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise CalibrationContractError("created_at must be a UTC ISO-8601 timestamp")
    return value


def _validate_round_metadata(metadata: RoundMetadata, *, expected_stage: CalibrationStage) -> None:
    if metadata.contract_version != CONTRACT_VERSION:
        raise CalibrationContractError(f"contract_version must be {CONTRACT_VERSION}")
    if metadata.stage != expected_stage:
        raise CalibrationContractError(f"stage must be {expected_stage.value}")
    if not metadata.round_name:
        raise CalibrationContractError("round must be non-empty")
    _validate_sha256(metadata.batch_sha256, field="batch_sha256")
    if not isinstance(metadata.canonical_job_count, int) or metadata.canonical_job_count <= 0:
        raise CalibrationContractError("canonical_job_count must be a positive integer count")
    _validate_created_at(metadata.created_at)
    if expected_stage == CalibrationStage.FIT:
        if metadata.interest_path is None:
            raise CalibrationContractError("interest_path metadata is required for fit stage")
        if metadata.interest_sha256 is None:
            raise CalibrationContractError("interest_sha256 metadata is required for fit stage")
        _validate_sha256(metadata.interest_sha256, field="interest_sha256")


def normalize_call(value: str, *, field: str, job_id: int, required: bool) -> str | None:
    if not isinstance(value, str):
        raise CalibrationContractError(f"job {job_id}: {field} must be text")
    normalized = value.strip().upper()
    if not normalized:
        if required:
            raise CalibrationContractError(f"job {job_id}: {field} is required")
        return None
    if normalized not in VALID_CALLS:
        raise CalibrationContractError(f"job {job_id}: invalid {field} {value!r}")
    return normalized


def render_interest_worksheet(metadata: RoundMetadata, jobs: tuple[BatchJob, ...]) -> str:
    _validate_round_metadata(metadata, expected_stage=CalibrationStage.INTEREST)
    if len(jobs) != metadata.canonical_job_count:
        raise CalibrationContractError(
            f"canonical_job_count {metadata.canonical_job_count} does not match jobs count {len(jobs)}"
        )
    rows = [
        "---",
        f"contract_version: {metadata.contract_version}",
        f"stage: {metadata.stage.value}",
        f'round: "{metadata.round_name}"',
        f'batch_path: "{_path_for_metadata(metadata.batch_path)}"',
        f'batch_sha256: "{metadata.batch_sha256}"',
        f"canonical_job_count: {metadata.canonical_job_count}",
        f'created_at: "{metadata.created_at}"',
        "---",
        "",
        "| id | row_ids | company | title | locations | flags | jd_quality | interest_call | notes |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for job in jobs:
        rows.append(
            "| "
            + " | ".join(
                [
                    str(job.job_id),
                    ",".join(str(row_id) for row_id in sorted(job.row_ids)),
                    encode_cell(job.company),
                    encode_cell(job.title),
                    encode_cell("; ".join(job.locations)),
                    encode_cell("; ".join(job.flags)),
                    job.jd_quality,
                    "",
                    "",
                ]
            )
            + " |"
        )
    return "\n".join(rows) + "\n"


def _split_front_matter(text: str, *, path: Path) -> tuple[dict[str, object], str]:
    if not text.startswith("---\n"):
        raise CalibrationContractError(f"{path}: missing front matter")
    end = text.find("\n---\n", 4)
    if end == -1:
        raise CalibrationContractError(f"{path}: malformed front matter")
    raw_yaml = text[4:end]
    try:
        loaded = yaml.safe_load(raw_yaml)
    except yaml.YAMLError as exc:
        raise CalibrationContractError(f"{path}: malformed front matter YAML") from exc
    if not isinstance(loaded, dict):
        raise CalibrationContractError(f"{path}: front matter metadata must be a mapping")
    return loaded, text[end + len("\n---\n") :]


def _parse_round_metadata(raw: dict[str, object], *, stage: CalibrationStage, include_interest: bool = False) -> RoundMetadata:
    required = {
        "contract_version",
        "stage",
        "round",
        "batch_path",
        "batch_sha256",
        "canonical_job_count",
        "created_at",
    }
    if include_interest:
        required |= {"interest_path", "interest_sha256"}
    extra = set(raw) - required
    missing = required - set(raw)
    if missing or extra:
        raise CalibrationContractError(f"metadata keys mismatch: missing={sorted(missing)} extra={sorted(extra)}")
    if raw["contract_version"] != CONTRACT_VERSION:
        raise CalibrationContractError(f"contract_version must be {CONTRACT_VERSION}")
    if raw["stage"] != stage.value:
        raise CalibrationContractError(f"stage must be {stage.value}")
    batch_path_raw = raw["batch_path"]
    if not isinstance(batch_path_raw, str):
        raise CalibrationContractError("batch_path metadata must be text")
    count = raw["canonical_job_count"]
    if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
        raise CalibrationContractError("canonical_job_count must be a positive integer count")
    metadata = RoundMetadata(
        contract_version=CONTRACT_VERSION,
        stage=stage,
        round_name=str(raw["round"]),
        batch_path=_resolve_artifact_path(batch_path_raw),
        batch_sha256=_validate_sha256(raw["batch_sha256"], field="batch_sha256"),
        canonical_job_count=count,
        created_at=_validate_created_at(raw["created_at"]),
        interest_path=_resolve_artifact_path(raw["interest_path"]) if include_interest and isinstance(raw.get("interest_path"), str) else None,
        interest_sha256=_validate_sha256(raw["interest_sha256"], field="interest_sha256") if include_interest else None,
    )
    return metadata


def _parse_table(body: str, *, expected_columns: tuple[str, ...], path: Path) -> list[dict[str, str]]:
    lines = [line.rstrip() for line in body.splitlines() if line.strip()]
    header_index = None
    header_cells: list[str] = []
    for index, line in enumerate(lines):
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if cells == list(expected_columns):
            header_index = index
            header_cells = cells
            break
        if "id" in cells and any(col in cells for col in ("interest_call", "fit_call", "your call")):
            raise CalibrationContractError(f"{path}: table columns do not match expected columns")
    if header_index is None:
        raise CalibrationContractError(f"{path}: missing expected table columns")
    rows: list[dict[str, str]] = []
    for line in lines[header_index + 1 :]:
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if cells and all(set(cell) <= {"-"} for cell in cells):
            continue
        if len(cells) != len(header_cells):
            raise CalibrationContractError(f"{path}: table row has wrong column count")
        rows.append(dict(zip(header_cells, cells, strict=True)))
    return rows


def _expected_interest_cells(job: BatchJob) -> dict[str, str]:
    return {
        "id": str(job.job_id),
        "row_ids": ",".join(str(row_id) for row_id in sorted(job.row_ids)),
        "company": job.company,
        "title": job.title,
        "locations": "; ".join(job.locations),
        "flags": "; ".join(job.flags),
        "jd_quality": job.jd_quality,
    }


def parse_interest_worksheet(path: str | Path, *, require_complete: bool) -> CalibrationWorksheet:
    artifact_path = Path(path)
    raw_metadata, body = _split_front_matter(artifact_path.read_text(encoding="utf-8"), path=artifact_path)
    metadata = _parse_round_metadata(raw_metadata, stage=CalibrationStage.INTEREST)
    if not metadata.batch_path.exists():
        raise CalibrationContractError(f"{artifact_path}: batch file does not exist: {metadata.batch_path}")
    if sha256_file(metadata.batch_path) != metadata.batch_sha256:
        raise CalibrationContractError(f"{artifact_path}: batch sha256 does not match metadata batch_sha256")
    jobs = load_batch(metadata.batch_path)
    if len(jobs) != metadata.canonical_job_count:
        raise CalibrationContractError(
            f"{artifact_path}: batch count {len(jobs)} does not match canonical_job_count {metadata.canonical_job_count}"
        )
    rows = _parse_table(body, expected_columns=_INTEREST_COLUMNS, path=artifact_path)
    if len(rows) != metadata.canonical_job_count:
        raise CalibrationContractError(
            f"{artifact_path}: row count {len(rows)} does not match canonical_job_count {metadata.canonical_job_count}"
        )
    labels: list[CalibrationLabel] = []
    seen_ids: set[int] = set()
    for row, job in zip(rows, jobs, strict=True):
        try:
            row_id = int(row["id"])
        except ValueError as exc:
            raise CalibrationContractError(f"{artifact_path}: invalid row id {row['id']!r}") from exc
        if row_id in seen_ids:
            raise CalibrationContractError(f"{artifact_path}: duplicate row id {row_id}")
        seen_ids.add(row_id)
        if row_id != job.job_id:
            raise CalibrationContractError(f"{artifact_path}: row order/id mismatch for job {job.job_id}")
        expected = _expected_interest_cells(job)
        for column, expected_value in expected.items():
            actual = decode_cell(row[column])
            if actual != expected_value:
                raise CalibrationContractError(
                    f"{artifact_path}: job {job.job_id} {column} mismatch: expected {expected_value!r}, got {actual!r}"
                )
        labels.append(
            CalibrationLabel(
                job=job,
                interest_call=normalize_call(
                    decode_cell(row["interest_call"]),
                    field="interest_call",
                    job_id=job.job_id,
                    required=require_complete,
                ),
                fit_call=None,
                notes=decode_cell(row["notes"]),
            )
        )
    if seen_ids != {job.job_id for job in jobs}:
        raise CalibrationContractError(f"{artifact_path}: missing or extra canonical rows")
    return CalibrationWorksheet(metadata=metadata, labels=tuple(labels))


def _escape_jd_markers(jd_text: str) -> str:
    return jd_text.replace(_JD_MARKER_PREFIX, _ESCAPED_JD_MARKER_PREFIX)


def _restore_jd_markers(jd_text: str) -> str:
    return jd_text.replace(_ESCAPED_JD_MARKER_PREFIX, _JD_MARKER_PREFIX)


def render_fit_worksheet(
    metadata: RoundMetadata,
    interest: CalibrationWorksheet,
    full_jds: tuple[FullJD, ...],
) -> str:
    _validate_round_metadata(metadata, expected_stage=CalibrationStage.FIT)
    if not isinstance(interest.metadata, RoundMetadata) or interest.metadata.stage != CalibrationStage.INTEREST:
        raise CalibrationContractError("fit worksheet requires a v2 interest worksheet")
    if metadata.interest_path is None or metadata.interest_sha256 is None:
        raise CalibrationContractError("fit metadata must include interest provenance")
    if len(full_jds) != len(interest.labels):
        raise CalibrationContractError("full JD count must match interest labels")
    full_by_id = {full.job_id: full for full in full_jds}
    if set(full_by_id) != {label.job.job_id for label in interest.labels}:
        raise CalibrationContractError("full JD IDs must match interest labels")

    rows = [
        "---",
        f"contract_version: {metadata.contract_version}",
        f"stage: {metadata.stage.value}",
        f'round: "{metadata.round_name}"',
        f'batch_path: "{_path_for_metadata(metadata.batch_path)}"',
        f'batch_sha256: "{metadata.batch_sha256}"',
        f"canonical_job_count: {metadata.canonical_job_count}",
        f'created_at: "{metadata.created_at}"',
        f'interest_path: "{_path_for_metadata(metadata.interest_path)}"',
        f'interest_sha256: "{metadata.interest_sha256}"',
        "---",
        "",
        "| id | row_ids | company | title | locations | flags | jd_quality | interest_call | fit_call | notes |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for label in interest.labels:
        job = label.job
        if label.interest_call is None:
            raise CalibrationContractError(f"job {job.job_id}: interest_call is required before fit reveal")
        full = full_by_id[job.job_id]
        if full.company != job.company or full.title != job.title:
            raise CalibrationContractError(f"job {job.job_id}: full JD company/title does not match batch")
        rows.append(
            "| "
            + " | ".join(
                [
                    str(job.job_id),
                    ",".join(str(row_id) for row_id in sorted(job.row_ids)),
                    encode_cell(job.company),
                    encode_cell(job.title),
                    encode_cell("; ".join(job.locations)),
                    encode_cell("; ".join(job.flags)),
                    job.jd_quality,
                    label.interest_call,
                    "",
                    "",
                ]
            )
            + " |"
        )
    rows.append("")
    for label in interest.labels:
        job = label.job
        full = full_by_id[job.job_id]
        if not full.jd_text:
            raise CalibrationContractError(f"job {job.job_id}: full JD text is missing")
        rows.extend(
            [
                f"## Job {job.job_id} — {job.company} — {job.title}",
                "",
                f"JD SHA-256: `{sha256_bytes(full.jd_text.encode('utf-8'))}`",
                "",
                f"<!-- CALIBRATION_JD_START id={job.job_id} -->",
                _escape_jd_markers(full.jd_text),
                f"<!-- CALIBRATION_JD_END id={job.job_id} -->",
                "",
            ]
        )
    return "\n".join(rows)


def _parse_jd_sections(body: str, *, expected_ids: tuple[int, ...], path: Path) -> dict[int, str]:
    starts = re.findall(r"<!-- CALIBRATION_JD_START id=(\d+) -->", body)
    ends = re.findall(r"<!-- CALIBRATION_JD_END id=(\d+) -->", body)
    if sorted(starts) != sorted(str(job_id) for job_id in expected_ids) or sorted(ends) != sorted(str(job_id) for job_id in expected_ids):
        raise CalibrationContractError(f"{path}: JD section markers do not match expected jobs")
    sections: dict[int, str] = {}
    for job_id in expected_ids:
        pattern = re.compile(
            rf"JD SHA-256: `([0-9a-f]{{64}})`\n\n<!-- CALIBRATION_JD_START id={job_id} -->\n(.*?)\n<!-- CALIBRATION_JD_END id={job_id} -->",
            re.DOTALL,
        )
        match = pattern.search(body)
        if match is None:
            raise CalibrationContractError(f"{path}: JD section missing or malformed for job {job_id}")
        expected_hash, rendered_text = match.groups()
        restored = _restore_jd_markers(rendered_text)
        actual_hash = sha256_bytes(restored.encode("utf-8"))
        if actual_hash != expected_hash:
            raise CalibrationContractError(f"{path}: job {job_id} JD SHA-256 mismatch")
        sections[job_id] = restored
    return sections


def parse_fit_worksheet(path: str | Path, *, require_complete: bool) -> CalibrationWorksheet:
    artifact_path = Path(path)
    raw_metadata, body = _split_front_matter(artifact_path.read_text(encoding="utf-8"), path=artifact_path)
    metadata = _parse_round_metadata(raw_metadata, stage=CalibrationStage.FIT, include_interest=True)
    if not metadata.batch_path.exists():
        raise CalibrationContractError(f"{artifact_path}: batch file does not exist: {metadata.batch_path}")
    if sha256_file(metadata.batch_path) != metadata.batch_sha256:
        raise CalibrationContractError(f"{artifact_path}: batch sha256 does not match metadata batch_sha256")
    if metadata.interest_path is None or metadata.interest_sha256 is None:
        raise CalibrationContractError(f"{artifact_path}: interest metadata missing")
    if sha256_file(metadata.interest_path) != metadata.interest_sha256:
        raise CalibrationContractError(f"{artifact_path}: interest_sha256 does not match current interest file")
    interest = parse_interest_worksheet(metadata.interest_path, require_complete=True)
    jobs = tuple(label.job for label in interest.labels)
    rows = _parse_table(body, expected_columns=_FIT_COLUMNS, path=artifact_path)
    if len(rows) != len(jobs):
        raise CalibrationContractError(f"{artifact_path}: fit row count does not match interest count")
    _parse_jd_sections(body, expected_ids=tuple(job.job_id for job in jobs), path=artifact_path)

    labels: list[CalibrationLabel] = []
    seen_ids: set[int] = set()
    for row, interest_label in zip(rows, interest.labels, strict=True):
        job = interest_label.job
        try:
            row_id = int(row["id"])
        except ValueError as exc:
            raise CalibrationContractError(f"{artifact_path}: invalid row id {row['id']!r}") from exc
        if row_id in seen_ids:
            raise CalibrationContractError(f"{artifact_path}: duplicate row id {row_id}")
        seen_ids.add(row_id)
        if row_id != job.job_id:
            raise CalibrationContractError(f"{artifact_path}: row order/id mismatch for job {job.job_id}")
        expected = _expected_interest_cells(job)
        for column, expected_value in expected.items():
            actual = decode_cell(row[column])
            if actual != expected_value:
                raise CalibrationContractError(
                    f"{artifact_path}: job {job.job_id} {column} mismatch: expected {expected_value!r}, got {actual!r}"
                )
        copied_interest = normalize_call(
            decode_cell(row["interest_call"]),
            field="interest_call",
            job_id=job.job_id,
            required=True,
        )
        if copied_interest != interest_label.interest_call:
            raise CalibrationContractError(f"{artifact_path}: job {job.job_id} copied interest_call changed")
        labels.append(
            CalibrationLabel(
                job=job,
                interest_call=copied_interest,
                fit_call=normalize_call(
                    decode_cell(row["fit_call"]),
                    field="fit_call",
                    job_id=job.job_id,
                    required=require_complete,
                ),
                notes=decode_cell(row["notes"]),
            )
        )
    return CalibrationWorksheet(metadata=metadata, labels=tuple(labels))
