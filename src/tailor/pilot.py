"""Pilot operator: composes existing, already-validated stage pipelines
into one resumable, idempotent, cost-accounted chain
(S1 -> S0 -> S2 -> S3 -> static G1 -> G2 -> render + L7 -> G3). Reimplements
no parsing, validation, or hydration of its own -- every stage's own
accepted artifact is the authority. The run manifest is rebuilt from
artifacts on every run and never trusted as the source of truth: a
corrupted or stale run_manifest.json cannot cause a stage to be skipped."""
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

MANIFEST_SCHEMA = "m8p7.run_manifest.v1"
APPLICATIONS_ROOT = Path("applications")


class Stage(str, Enum):
    PREPARE = "prepare"
    S1 = "s1"
    S0 = "s0"
    S2 = "s2"
    S3 = "s3"
    G2 = "g2"
    RENDER = "render"
    G3 = "g3"


STAGE_ORDER: tuple[Stage, ...] = (
    Stage.PREPARE, Stage.S1, Stage.S0, Stage.S2, Stage.S3, Stage.G2, Stage.RENDER, Stage.G3,
)

#: Stage -> accepted artifact filename, per spec §3.2's artifact layout.
STAGE_ARTIFACT: dict[Stage, str] = {
    Stage.PREPARE: "s1_request.json",
    Stage.S1: "s1_response.json",
    Stage.S0: "s0_response.json",
    Stage.S2: "s2_response.json",
    Stage.S3: "s3_bundle.json",
    Stage.G2: "g2_bundle.json",
    Stage.RENDER: "render_result.json",
    Stage.G3: "packet.json",
}

#: alignment_fingerprint exists from S2 onward only (spec §3.2).
_STAGES_WITHOUT_FINGERPRINT = frozenset({Stage.PREPARE, Stage.S1, Stage.S0})


class StageState(str, Enum):
    PENDING = "pending"
    SKIPPED_COMPLETE = "skipped_complete"
    COMPLETE = "complete"
    CONFLICT = "conflict"
    FAILED = "failed"


class PilotManifestError(ValueError):
    """Raised when a persisted run_manifest.json cannot be parsed. Never
    raised by rebuild_manifest itself -- a stale or corrupted manifest is
    simply ignored and rebuilt from the artifacts."""


def bounded(value: object, limit: int = 200) -> str:
    text = str(value)
    return text if len(text) <= limit else text[:limit] + "..."


@dataclass(frozen=True)
class StageRecord:
    stage: Stage
    state: StageState
    outcome_kind: str
    artifact_path: str | None
    model_calls: int
    trace_paths: tuple[str, ...]
    started_at: str
    ended_at: str
    error: str | None


@dataclass(frozen=True)
class RunManifest:
    schema_version: str
    job_id: int
    company: str
    title: str
    alignment_fingerprint: str | None
    stages: tuple[StageRecord, ...]
    total_model_calls: int
    db_mutations: int
    submissions: int


def artifact_path(directory: Path, stage: Stage) -> Path:
    return Path(directory) / STAGE_ARTIFACT[stage]


def _read_json_or_none(path: Path) -> object | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def stage_is_complete(
    directory: Path, stage: Stage, *, job_id: int, alignment_fingerprint: str | None,
) -> bool:
    """True only if the stage's own accepted artifact exists, is valid
    JSON, and its bound identity (job_id, and alignment_fingerprint from S2
    onward) matches exactly. Any read or parse error means "not complete",
    never a crash."""
    path = artifact_path(directory, stage)
    if not path.exists():
        return False
    raw = _read_json_or_none(path)
    if not isinstance(raw, dict):
        return False
    if raw.get("job_id") != job_id:
        return False
    if stage not in _STAGES_WITHOUT_FINGERPRINT:
        if alignment_fingerprint is None or raw.get("alignment_fingerprint") != alignment_fingerprint:
            return False
    return True


def _discover_fingerprint(directory: Path, job_id: int) -> str | None:
    """The real, already-accepted fingerprint, read from whichever S2+
    artifact exists and matches job_id -- never supplied by the caller,
    since the whole point is to bind against what was actually accepted."""
    fingerprint: str | None = None
    for stage in STAGE_ORDER:
        if stage in _STAGES_WITHOUT_FINGERPRINT:
            continue
        raw = _read_json_or_none(artifact_path(directory, stage))
        if isinstance(raw, dict) and raw.get("job_id") == job_id and isinstance(raw.get("alignment_fingerprint"), str):
            fingerprint = raw["alignment_fingerprint"]
    return fingerprint


def rebuild_manifest(directory: Path, *, job_id: int, company: str, title: str) -> RunManifest:
    """Walk STAGE_ORDER; never reads run_manifest.json. Each stage's
    completeness is checked independently against its own artifact -- there
    is no cascading "first incomplete stage blocks the rest" logic, because
    an artifact's own identity match is sufficient proof of acceptance
    regardless of any other stage's state."""
    directory = Path(directory)
    alignment_fingerprint = _discover_fingerprint(directory, job_id)

    stages: list[StageRecord] = []
    for stage in STAGE_ORDER:
        complete = stage_is_complete(
            directory, stage, job_id=job_id, alignment_fingerprint=alignment_fingerprint,
        )
        state = StageState.SKIPPED_COMPLETE if complete else StageState.PENDING
        stages.append(StageRecord(
            stage=stage, state=state, outcome_kind=state.value,
            artifact_path=str(artifact_path(directory, stage)) if complete else None,
            model_calls=0, trace_paths=(), started_at="", ended_at="", error=None,
        ))

    return RunManifest(
        schema_version=MANIFEST_SCHEMA, job_id=job_id, company=company, title=title,
        alignment_fingerprint=alignment_fingerprint, stages=tuple(stages),
        total_model_calls=0, db_mutations=0, submissions=0,
    )


def stage_record_to_dict(record: StageRecord) -> dict[str, object]:
    return {
        "stage": record.stage.value, "state": record.state.value, "outcome_kind": record.outcome_kind,
        "artifact_path": record.artifact_path, "model_calls": record.model_calls,
        "trace_paths": list(record.trace_paths), "started_at": record.started_at,
        "ended_at": record.ended_at, "error": record.error,
    }


def manifest_to_dict(manifest: RunManifest) -> dict[str, object]:
    return {
        "schema_version": manifest.schema_version, "job_id": manifest.job_id,
        "company": manifest.company, "title": manifest.title,
        "alignment_fingerprint": manifest.alignment_fingerprint,
        "stages": [stage_record_to_dict(record) for record in manifest.stages],
        "total_model_calls": manifest.total_model_calls,
        "db_mutations": manifest.db_mutations, "submissions": manifest.submissions,
    }


_MANIFEST_KEYS = {
    "schema_version", "job_id", "company", "title", "alignment_fingerprint", "stages",
    "total_model_calls", "db_mutations", "submissions",
}
_STAGE_RECORD_KEYS = {
    "stage", "state", "outcome_kind", "artifact_path", "model_calls", "trace_paths",
    "started_at", "ended_at", "error",
}


def parse_stage_record(raw: object) -> StageRecord:
    if not isinstance(raw, dict) or set(raw) != _STAGE_RECORD_KEYS:
        raise PilotManifestError("$: unexpected field set for a stage record")
    return StageRecord(
        stage=Stage(raw["stage"]), state=StageState(raw["state"]), outcome_kind=raw["outcome_kind"],
        artifact_path=raw["artifact_path"], model_calls=raw["model_calls"],
        trace_paths=tuple(raw["trace_paths"]), started_at=raw["started_at"], ended_at=raw["ended_at"],
        error=raw["error"],
    )


def parse_manifest(raw: object) -> RunManifest:
    if not isinstance(raw, dict) or set(raw) != _MANIFEST_KEYS:
        raise PilotManifestError("$: unexpected field set for a run manifest")
    return RunManifest(
        schema_version=raw["schema_version"], job_id=raw["job_id"], company=raw["company"],
        title=raw["title"], alignment_fingerprint=raw["alignment_fingerprint"],
        stages=tuple(parse_stage_record(item) for item in raw["stages"]),
        total_model_calls=raw["total_model_calls"], db_mutations=raw["db_mutations"],
        submissions=raw["submissions"],
    )
