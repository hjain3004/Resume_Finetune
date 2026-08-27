"""Pilot operator: composes existing, already-validated stage pipelines
into one resumable, idempotent, cost-accounted chain
(S1 -> S0 -> S2 -> S3 -> static G1 -> G2 -> render + L7 -> G3). Reimplements
no parsing, validation, or hydration of its own -- every stage's own
accepted artifact is the authority. The run manifest is rebuilt from
artifacts on every run and never trusted as the source of truth: a
corrupted or stale run_manifest.json cannot cause a stage to be skipped."""
from __future__ import annotations

import datetime
import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from src import db
from src.profile import load_profile
from src.tailor.alignment_view import alignment_from_profile
from src.tailor.artifacts import write_json_atomic
from src.tailor.feedback import DEFAULT_FEEDBACK_DIR, load_feedback_index
from src.tailor.g1 import load_banned_terms
from src.tailor.g2 import load_taste_lessons
from src.tailor.g2_pipeline import G2OutcomeKind, g2_bundle_to_dict, parse_g2_bundle, run_g2_loop
from src.tailor.g3 import G3OutcomeKind, build_review_packet, publish_packet
from src.tailor.publish import RenderOutcomeKind, application_dir, parse_render_result, render_and_publish
from src.tailor.s0 import S0Response, build_s0_request, parse_s0_response, s0_response_to_dict
from src.tailor.s0_pipeline import S0OutcomeKind, run_s0_invocation
from src.tailor.s1 import S1Response, parse_s1_request, parse_s1_response, s1_request_to_dict, s1_response_to_dict
from src.tailor.s1_pipeline import S1OutcomeKind, run_s1_invocation
from src.tailor.s2 import S2Response, build_s2_request, parse_s2_response, s2_response_to_dict
from src.tailor.s2_pipeline import S2OutcomeKind, run_s2_invocation
from src.tailor.s3 import build_s3_request
from src.tailor.s3_pipeline import S3OutcomeKind, parse_s3_bundle, run_s3_invocation, s3_bundle_to_dict

DEFAULT_PROMPT_DIR = Path("docs/prompts")

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


def stage_record_from_dict(raw: object) -> StageRecord:
    if not isinstance(raw, dict) or set(raw) != _STAGE_RECORD_KEYS:
        raise PilotManifestError("$: unexpected field set for a stage record")
    return StageRecord(
        stage=Stage(raw["stage"]), state=StageState(raw["state"]), outcome_kind=raw["outcome_kind"],
        artifact_path=raw["artifact_path"], model_calls=raw["model_calls"],
        trace_paths=tuple(raw["trace_paths"]), started_at=raw["started_at"], ended_at=raw["ended_at"],
        error=raw["error"],
    )


def manifest_from_dict(raw: object) -> RunManifest:
    if not isinstance(raw, dict) or set(raw) != _MANIFEST_KEYS:
        raise PilotManifestError("$: unexpected field set for a run manifest")
    return RunManifest(
        schema_version=raw["schema_version"], job_id=raw["job_id"], company=raw["company"],
        title=raw["title"], alignment_fingerprint=raw["alignment_fingerprint"],
        stages=tuple(stage_record_from_dict(item) for item in raw["stages"]),
        total_model_calls=raw["total_model_calls"], db_mutations=raw["db_mutations"],
        submissions=raw["submissions"],
    )


# ---------------------------------------------------------------------------
# Chain driver. Composes the existing stage pipelines; performs no parsing,
# validation, or hydration of its own.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RunOutcome:
    manifest: RunManifest
    failed_stage: Stage | None
    retry_command: str | None


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _envelope(job_id: int, response_dict: dict, alignment_fingerprint: str | None = None) -> dict:
    """S1Response/S0Response/S2Response carry no identity of their own --
    the operator's own on-disk envelope binds job_id (and, from S2 on,
    alignment_fingerprint) around the stage's real serialized content."""
    envelope: dict[str, object] = {"job_id": job_id, "response": response_dict}
    if alignment_fingerprint is not None:
        envelope["alignment_fingerprint"] = alignment_fingerprint
    return envelope


def run_application(
    job_id: int, *, db_path: Path, profile_path: Path,
    root: Path = APPLICATIONS_ROOT,
    template_path: Path = Path("profile/template.tex"),
    banned_words_path: Path = Path("config/banned_words.txt"),
    taste_path: Path = Path("config/taste.md"),
    trace_dir: Path = Path("data/traces"),
    feedback_dir: Path = DEFAULT_FEEDBACK_DIR,
    prompt_dir: Path = DEFAULT_PROMPT_DIR,
    stop_after: Stage | None = None,
    only: Stage | None = None,
    dry_run: bool = False,
    allow_rerun_after_feedback: bool = False,
) -> RunOutcome:
    stage_records: list[StageRecord] = []
    total_model_calls = 0
    company = ""
    title = ""
    alignment_fingerprint: str | None = None
    directory: Path | None = None
    effective_stop_after = only if only is not None else stop_after

    def record(stage: Stage, state: StageState, outcome_kind: str, *, started: str, artifact: Path | None = None,
              model_calls: int = 0, trace_paths: tuple = (), error: str | None = None) -> None:
        stage_records.append(StageRecord(
            stage=stage, state=state, outcome_kind=outcome_kind,
            artifact_path=str(artifact) if artifact is not None else None,
            model_calls=model_calls, trace_paths=tuple(str(t) for t in trace_paths if t is not None),
            started_at=started, ended_at=_now(), error=bounded(error) if error is not None else None,
        ))

    def finish(failed_stage: Stage | None) -> RunOutcome:
        manifest = RunManifest(
            schema_version=MANIFEST_SCHEMA, job_id=job_id, company=company, title=title,
            alignment_fingerprint=alignment_fingerprint, stages=tuple(stage_records),
            total_model_calls=total_model_calls, db_mutations=0, submissions=0,
        )
        if directory is not None and not dry_run:
            write_json_atomic(directory / "run_manifest.json", manifest_to_dict(manifest))
        retry_command = (
            f"python -m scripts.tailor_pilot run --job-id {job_id} --only {failed_stage.value}"
            if failed_stage is not None else None
        )
        return RunOutcome(manifest=manifest, failed_stage=failed_stage, retry_command=retry_command)

    # ---- PREPARE ----
    started = _now()
    if not allow_rerun_after_feedback:
        if any(entry.get("job_id") == job_id for entry in load_feedback_index(feedback_dir)):
            record(Stage.PREPARE, StageState.FAILED, "feedback_recorded", started=started,
                  error="feedback already recorded for this job; rerun refused (use --allow-rerun-after-feedback)")
            return finish(Stage.PREPARE)

    conn = db.get_readonly_connection(db_path)
    try:
        try:
            s1_request = db.prepare_tailoring_request(conn, job_id)
            variant = db.tailoring_base_variant(conn, job_id)
        except Exception as exc:
            record(Stage.PREPARE, StageState.FAILED, "prepare_failure", started=started, error=str(exc))
            return finish(Stage.PREPARE)
    finally:
        conn.close()

    company, title = s1_request.company, s1_request.title
    directory = application_dir(root, company, title)
    if allow_rerun_after_feedback and any(
        entry.get("job_id") == job_id for entry in load_feedback_index(feedback_dir)
    ):
        n = 1
        while (directory / f"rerun-{n}").exists():
            n += 1
        directory = directory / f"rerun-{n}"

    prepare_exists = artifact_path(directory, Stage.PREPARE).exists()
    prepare_complete = stage_is_complete(directory, Stage.PREPARE, job_id=job_id, alignment_fingerprint=None)
    if prepare_complete:
        record(Stage.PREPARE, StageState.SKIPPED_COMPLETE, "skipped_complete", started=started,
              artifact=artifact_path(directory, Stage.PREPARE))
    elif prepare_exists:
        record(Stage.PREPARE, StageState.CONFLICT, "conflict", started=started,
              error="s1_request.json exists but does not match this job_id")
        return finish(Stage.PREPARE)
    elif dry_run:
        record(Stage.PREPARE, StageState.PENDING, "pending", started=started)
        return finish(None)
    else:
        write_json_atomic(artifact_path(directory, Stage.PREPARE), s1_request_to_dict(s1_request))
        record(Stage.PREPARE, StageState.COMPLETE, "complete", started=started,
              artifact=artifact_path(directory, Stage.PREPARE))
    if effective_stop_after is Stage.PREPARE:
        return finish(None)

    # ---- S1 ----
    started = _now()
    s1_exists = artifact_path(directory, Stage.S1).exists()
    s1_complete = stage_is_complete(directory, Stage.S1, job_id=job_id, alignment_fingerprint=None)
    if s1_complete:
        raw = json.loads(artifact_path(directory, Stage.S1).read_text(encoding="utf-8"))
        s1 = parse_s1_response(json.dumps(raw["response"]), s1_request.jd_text)
        record(Stage.S1, StageState.SKIPPED_COMPLETE, "skipped_complete", started=started,
              artifact=artifact_path(directory, Stage.S1))
    elif s1_exists:
        record(Stage.S1, StageState.CONFLICT, "conflict", started=started,
              error="s1_response.json exists but does not match this job_id")
        return finish(Stage.S1)
    elif dry_run:
        record(Stage.S1, StageState.PENDING, "pending", started=started)
        return finish(None)
    else:
        outcome = run_s1_invocation(
            s1_request, prompt_template_path=prompt_dir / "tailoring_s1.md",
            request_path=artifact_path(directory, Stage.PREPARE), trace_dir=trace_dir,
        )
        total_model_calls += 1
        if outcome.kind is not S1OutcomeKind.VALID:
            record(Stage.S1, StageState.FAILED, outcome.kind.value, started=started, model_calls=1,
                  trace_paths=(outcome.trace_path,), error=outcome.error)
            return finish(Stage.S1)
        s1 = outcome.response
        write_json_atomic(artifact_path(directory, Stage.S1), _envelope(job_id, s1_response_to_dict(s1)))
        record(Stage.S1, StageState.COMPLETE, outcome.kind.value, started=started,
              artifact=artifact_path(directory, Stage.S1), model_calls=1,
              trace_paths=(outcome.trace_path,))
    if effective_stop_after is Stage.S1:
        return finish(None)

    # ---- S0 ----
    started = _now()
    profile = load_profile(profile_path)
    positioning = profile.for_positioning()
    s0_request = build_s0_request(job_id, company, title, s1, positioning)
    s0_exists = artifact_path(directory, Stage.S0).exists()
    s0_complete = stage_is_complete(directory, Stage.S0, job_id=job_id, alignment_fingerprint=None)
    if s0_complete:
        raw = json.loads(artifact_path(directory, Stage.S0).read_text(encoding="utf-8"))
        s0 = parse_s0_response(json.dumps(raw["response"]), s0_request)
        record(Stage.S0, StageState.SKIPPED_COMPLETE, "skipped_complete", started=started,
              artifact=artifact_path(directory, Stage.S0))
    elif s0_exists:
        record(Stage.S0, StageState.CONFLICT, "conflict", started=started,
              error="s0_response.json exists but does not match this job_id")
        return finish(Stage.S0)
    elif dry_run:
        record(Stage.S0, StageState.PENDING, "pending", started=started)
        return finish(None)
    else:
        outcome = run_s0_invocation(
            s0_request, prompt_template_path=prompt_dir / "tailoring_s0.md",
            request_path=artifact_path(directory, Stage.S1), trace_dir=trace_dir,
        )
        total_model_calls += 1
        if outcome.kind is not S0OutcomeKind.VALID:
            record(Stage.S0, StageState.FAILED, outcome.kind.value, started=started, model_calls=1,
                  trace_paths=(outcome.trace_path,), error=outcome.error)
            return finish(Stage.S0)
        s0 = outcome.response
        write_json_atomic(artifact_path(directory, Stage.S0), _envelope(job_id, s0_response_to_dict(s0)))
        record(Stage.S0, StageState.COMPLETE, outcome.kind.value, started=started,
              artifact=artifact_path(directory, Stage.S0), model_calls=1,
              trace_paths=(outcome.trace_path,))
    if effective_stop_after is Stage.S0:
        return finish(None)

    # ---- S2 ----
    started = _now()
    catalog = profile.for_selection(variant)
    s2_request = build_s2_request(job_id, company, title, s1, s0, catalog)
    s2_exists = artifact_path(directory, Stage.S2).exists()
    # S2's own completeness needs the alignment fingerprint, which is only
    # knowable once S2 has actually produced a response -- so probe with
    # whatever fingerprint (if any) the persisted file itself carries.
    persisted_s2_fingerprint = None
    if s2_exists:
        raw_peek = json.loads(artifact_path(directory, Stage.S2).read_text(encoding="utf-8")) if s2_exists else None
        if isinstance(raw_peek, dict):
            persisted_s2_fingerprint = raw_peek.get("alignment_fingerprint")
    s2_complete = s2_exists and stage_is_complete(
        directory, Stage.S2, job_id=job_id, alignment_fingerprint=persisted_s2_fingerprint,
    )
    if s2_complete:
        raw = json.loads(artifact_path(directory, Stage.S2).read_text(encoding="utf-8"))
        s2 = parse_s2_response(json.dumps(raw["response"]), s2_request)
        recomputed = alignment_from_profile(profile, s2_request, s2)
        if recomputed.fingerprint != raw["alignment_fingerprint"]:
            record(Stage.S2, StageState.CONFLICT, "conflict", started=started,
                  error="s2_response.json's alignment_fingerprint no longer matches the current profile")
            return finish(Stage.S2)
        alignment_fingerprint = recomputed.fingerprint
        alignment = recomputed
        record(Stage.S2, StageState.SKIPPED_COMPLETE, "skipped_complete", started=started,
              artifact=artifact_path(directory, Stage.S2))
    elif s2_exists:
        record(Stage.S2, StageState.CONFLICT, "conflict", started=started,
              error="s2_response.json exists but does not match this job_id")
        return finish(Stage.S2)
    elif dry_run:
        record(Stage.S2, StageState.PENDING, "pending", started=started)
        return finish(None)
    else:
        outcome = run_s2_invocation(
            s2_request, prompt_template_path=prompt_dir / "tailoring_s2.md",
            request_path=artifact_path(directory, Stage.S0), trace_dir=trace_dir,
        )
        total_model_calls += 1
        if outcome.kind is not S2OutcomeKind.VALID:
            record(Stage.S2, StageState.FAILED, outcome.kind.value, started=started, model_calls=1,
                  trace_paths=(outcome.trace_path,), error=outcome.error)
            return finish(Stage.S2)
        s2 = outcome.response
        alignment = alignment_from_profile(profile, s2_request, s2)
        alignment_fingerprint = alignment.fingerprint
        write_json_atomic(
            artifact_path(directory, Stage.S2),
            _envelope(job_id, s2_response_to_dict(s2), alignment_fingerprint),
        )
        record(Stage.S2, StageState.COMPLETE, outcome.kind.value, started=started,
              artifact=artifact_path(directory, Stage.S2), model_calls=1,
              trace_paths=(outcome.trace_path,))
    if effective_stop_after is Stage.S2:
        return finish(None)

    # ---- S3 ----
    started = _now()
    s3_request = build_s3_request(job_id, company, title, s1, s0, s2, alignment)
    banned_terms = load_banned_terms(banned_words_path)
    s3_exists = artifact_path(directory, Stage.S3).exists()
    s3_complete = stage_is_complete(
        directory, Stage.S3, job_id=job_id, alignment_fingerprint=alignment_fingerprint,
    )
    if s3_complete:
        raw = json.loads(artifact_path(directory, Stage.S3).read_text(encoding="utf-8"))
        s3_bundle = parse_s3_bundle(raw, s3_request, banned_terms)
        record(Stage.S3, StageState.SKIPPED_COMPLETE, "skipped_complete", started=started,
              artifact=artifact_path(directory, Stage.S3))
    elif s3_exists:
        record(Stage.S3, StageState.CONFLICT, "conflict", started=started,
              error="s3_bundle.json exists but does not match this job's alignment_fingerprint")
        return finish(Stage.S3)
    elif dry_run:
        record(Stage.S3, StageState.PENDING, "pending", started=started)
        return finish(None)
    else:
        outcome = run_s3_invocation(
            s3_request, prompt_template_path=prompt_dir / "tailoring_s3.md",
            request_path=artifact_path(directory, Stage.S2), banned_terms=banned_terms, trace_dir=trace_dir,
        )
        total_model_calls += 1
        if outcome.kind is not S3OutcomeKind.VALID:
            record(Stage.S3, StageState.FAILED, outcome.kind.value, started=started, model_calls=1,
                  trace_paths=(outcome.trace_path,), error=outcome.error)
            return finish(Stage.S3)
        s3_bundle = outcome.bundle
        write_json_atomic(artifact_path(directory, Stage.S3), s3_bundle_to_dict(s3_bundle))
        record(Stage.S3, StageState.COMPLETE, outcome.kind.value, started=started,
              artifact=artifact_path(directory, Stage.S3), model_calls=1,
              trace_paths=(outcome.trace_path,))
    if effective_stop_after is Stage.S3:
        return finish(None)

    # ---- G2 ----
    started = _now()
    g2_exists = artifact_path(directory, Stage.G2).exists()
    g2_complete = stage_is_complete(
        directory, Stage.G2, job_id=job_id, alignment_fingerprint=alignment_fingerprint,
    )
    if g2_complete:
        raw = json.loads(artifact_path(directory, Stage.G2).read_text(encoding="utf-8"))
        g2_bundle = parse_g2_bundle(raw)
        record(Stage.G2, StageState.SKIPPED_COMPLETE, "skipped_complete", started=started,
              artifact=artifact_path(directory, Stage.G2))
    elif g2_exists:
        record(Stage.G2, StageState.CONFLICT, "conflict", started=started,
              error="g2_bundle.json exists but does not match this job's alignment_fingerprint")
        return finish(Stage.G2)
    elif dry_run:
        record(Stage.G2, StageState.PENDING, "pending", started=started)
        return finish(None)
    else:
        taste_lessons = load_taste_lessons(taste_path) if Path(taste_path).exists() else ()
        outcome = run_g2_loop(
            s3_request, s3_bundle,
            prompt_template_path=prompt_dir / "tailoring_g2.md",
            s3_prompt_template_path=prompt_dir / "tailoring_s3.md",
            request_path=artifact_path(directory, Stage.S3), banned_terms=banned_terms,
            taste_lessons=taste_lessons, trace_dir=trace_dir,
        )
        calls = outcome.bundle.model_calls if outcome.bundle is not None else 1
        total_model_calls += calls
        if outcome.kind not in (G2OutcomeKind.PASSED_ROUND_1, G2OutcomeKind.PASSED_ROUND_2, G2OutcomeKind.OPEN_FLAGS):
            record(Stage.G2, StageState.FAILED, outcome.kind.value, started=started, model_calls=calls,
                  trace_paths=outcome.trace_paths, error=outcome.error)
            return finish(Stage.G2)
        g2_bundle = outcome.bundle
        write_json_atomic(artifact_path(directory, Stage.G2), g2_bundle_to_dict(g2_bundle))
        record(Stage.G2, StageState.COMPLETE, outcome.kind.value, started=started,
              artifact=artifact_path(directory, Stage.G2), model_calls=calls,
              trace_paths=outcome.trace_paths)
    if effective_stop_after is Stage.G2:
        return finish(None)

    # ---- RENDER ----
    started = _now()
    render_exists = artifact_path(directory, Stage.RENDER).exists()
    render_complete = stage_is_complete(
        directory, Stage.RENDER, job_id=job_id, alignment_fingerprint=alignment_fingerprint,
    )
    if render_complete:
        render_result = parse_render_result(json.loads(artifact_path(directory, Stage.RENDER).read_text(encoding="utf-8")))
        record(Stage.RENDER, StageState.SKIPPED_COMPLETE, "skipped_complete", started=started,
              artifact=artifact_path(directory, Stage.RENDER))
    elif render_exists:
        record(Stage.RENDER, StageState.CONFLICT, "conflict", started=started,
              error="render_result.json exists but does not match this job's alignment_fingerprint")
        return finish(Stage.RENDER)
    elif dry_run:
        record(Stage.RENDER, StageState.PENDING, "pending", started=started)
        return finish(None)
    else:
        canonical_text_by_id = {b.bullet_id: b.plain_text for b in s3_request.alignment.bullets}
        render_outcome = render_and_publish(
            profile, g2_bundle.accepted_s3_bundle.draft, root=root, template_path=template_path,
            canonical_text_by_id=canonical_text_by_id,
            s3_bundle_schema_version=g2_bundle.accepted_s3_bundle.schema_version,
        )
        if render_outcome.kind not in (RenderOutcomeKind.VALID, RenderOutcomeKind.ALREADY_PUBLISHED):
            record(Stage.RENDER, StageState.FAILED, render_outcome.kind.value, started=started,
                  error=render_outcome.error or "; ".join(render_outcome.violations))
            return finish(Stage.RENDER)
        render_result = render_outcome.result
        record(Stage.RENDER, StageState.COMPLETE, render_outcome.kind.value, started=started,
              artifact=artifact_path(directory, Stage.RENDER))
    if effective_stop_after is Stage.RENDER:
        return finish(None)

    # ---- G3 ----
    started = _now()
    g3_exists = artifact_path(directory, Stage.G3).exists()
    g3_complete = stage_is_complete(
        directory, Stage.G3, job_id=job_id, alignment_fingerprint=alignment_fingerprint,
    )
    if g3_complete:
        record(Stage.G3, StageState.SKIPPED_COMPLETE, "skipped_complete", started=started,
              artifact=artifact_path(directory, Stage.G3))
    elif g3_exists:
        record(Stage.G3, StageState.CONFLICT, "conflict", started=started,
              error="packet.json exists but does not match this job's alignment_fingerprint")
        return finish(Stage.G3)
    elif dry_run:
        record(Stage.G3, StageState.PENDING, "pending", started=started)
        return finish(None)
    else:
        packet = build_review_packet(g2_bundle.accepted_s3_bundle, g2_bundle, render_result, s1, s0, s2)
        changed_bullet_ids = tuple(edit.bullet_id for edit in g2_bundle.accepted_s3_bundle.response.bullet_edits)
        g3_outcome = publish_packet(packet, changed_bullet_ids, directory)
        if g3_outcome.kind not in (G3OutcomeKind.BUILT, G3OutcomeKind.ALREADY_BUILT):
            record(Stage.G3, StageState.FAILED, g3_outcome.kind.value, started=started, error=g3_outcome.error)
            return finish(Stage.G3)
        record(Stage.G3, StageState.COMPLETE, g3_outcome.kind.value, started=started,
              artifact=artifact_path(directory, Stage.G3))

    return finish(None)
