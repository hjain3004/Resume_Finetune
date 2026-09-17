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
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path

from src import db
from src.profile import load_profile
from src.tailor.alignment_view import alignment_from_profile
from src.tailor.artifacts import write_json_atomic
from src.tailor.feedback import DEFAULT_FEEDBACK_DIR, load_feedback_index, parse_feedback_record, summarize_feedback
from src.tailor.g1 import load_banned_terms
from src.tailor.g2 import load_taste_lessons
from src.tailor.g2_pipeline import G2OutcomeKind, g2_bundle_to_dict, parse_g2_bundle, run_g2_loop
from src.tailor.g3 import G3OutcomeKind, build_review_packet, publish_packet
from src.tailor.invoke import DEFAULT_CLAUDE_CMD
from src.tailor.providers import ModelCommand, Provider, build_model_command
from src.tailor.publish import RenderOutcomeKind, application_dir, parse_render_result, render_and_publish
from src.tailor.s0 import S0Response, build_s0_request, parse_s0_response, s0_response_to_dict
from src.tailor.s0_pipeline import S0OutcomeKind, run_s0_invocation
from src.tailor.s1 import (
    S1Request,
    S1Response,
    parse_s1_request,
    parse_s1_response,
    s1_request_to_dict,
    s1_response_to_dict,
)
from src.tailor.s1_pipeline import S1OutcomeKind, run_s1_invocation
from src.tailor.s2 import S2Response, build_s2_request, parse_s2_response, s2_response_to_dict
from src.tailor.s2_pipeline import S2OutcomeKind, run_s2_invocation
from src.tailor.s3 import build_s3_request, s3_request_to_dict
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


def _prepare_failure(job_id: int, outcome_kind: str, error: str, started: str) -> RunOutcome:
    """A PREPARE-stage failure that happens before any application directory
    is resolved (feedback refusal, DB read failure): one FAILED PREPARE
    record, empty company/title, no retry command, nothing written to disk."""
    record = StageRecord(
        stage=Stage.PREPARE, state=StageState.FAILED, outcome_kind=outcome_kind, artifact_path=None,
        model_calls=0, trace_paths=(), started_at=started, ended_at=_now(), error=bounded(error),
    )
    manifest = RunManifest(
        schema_version=MANIFEST_SCHEMA, job_id=job_id, company="", title="", alignment_fingerprint=None,
        stages=(record,), total_model_calls=0, db_mutations=0, submissions=0,
    )
    return RunOutcome(manifest=manifest, failed_stage=Stage.PREPARE, retry_command=None)


def run_application(
    job_id: int, *, db_path: Path, profile_path: Path,
    root: Path = APPLICATIONS_ROOT,
    template_path: Path = Path("profile/template.tex"),
    banned_words_path: Path = Path("config/banned_words.txt"),
    assumed_baseline_terms_path: Path = Path("config/assumed_baseline_terms.txt"),
    taste_path: Path = Path("config/taste.md"),
    trace_dir: Path = Path("data/traces"),
    feedback_dir: Path = DEFAULT_FEEDBACK_DIR,
    prompt_dir: Path = DEFAULT_PROMPT_DIR,
    stop_after: Stage | None = None,
    only: Stage | None = None,
    dry_run: bool = False,
    allow_rerun_after_feedback: bool = False,
) -> RunOutcome:
    started = _now()
    if not allow_rerun_after_feedback:
        if any(entry.get("job_id") == job_id for entry in load_feedback_index(feedback_dir)):
            return _prepare_failure(
                job_id, "feedback_recorded",
                "feedback already recorded for this job; rerun refused (use --allow-rerun-after-feedback)", started,
            )

    conn = db.get_readonly_connection(db_path)
    try:
        try:
            s1_request = db.prepare_tailoring_request(conn, job_id)
            variant = db.tailoring_base_variant(conn, job_id)
        except Exception as exc:
            return _prepare_failure(job_id, "prepare_failure", str(exc), started)
    finally:
        conn.close()

    directory = application_dir(root, s1_request.company, s1_request.title)
    if allow_rerun_after_feedback and any(
        entry.get("job_id") == job_id for entry in load_feedback_index(feedback_dir)
    ):
        n = 1
        while (directory / f"rerun-{n}").exists():
            n += 1
        directory = directory / f"rerun-{n}"

    return run_stages(
        s1_request, variant, directory=directory, profile_path=profile_path, root=root,
        template_path=template_path, banned_words_path=banned_words_path, taste_path=taste_path,
        assumed_baseline_terms_path=assumed_baseline_terms_path,
        trace_dir=trace_dir, prompt_dir=prompt_dir, stop_after=stop_after, only=only, dry_run=dry_run,
    )


def run_stages(
    s1_request: S1Request, variant: str, *,
    directory: Path, profile_path: Path, root: Path,
    template_path: Path = Path("profile/template.tex"),
    banned_words_path: Path = Path("config/banned_words.txt"),
    assumed_baseline_terms_path: Path = Path("config/assumed_baseline_terms.txt"),
    taste_path: Path = Path("config/taste.md"),
    trace_dir: Path = Path("data/traces"),
    prompt_dir: Path = DEFAULT_PROMPT_DIR,
    stop_after: Stage | None = None, only: Stage | None = None, dry_run: bool = False,
    command: ModelCommand | None = None,
    model_command: ModelCommand | None = None,
    claude_cmd: tuple[str, ...] | None = None,
    reject_dir: Path | None = None,
    retry_prefix: str | None = None,
) -> RunOutcome:
    effective_model_cmd = model_command if model_command is not None else command
    if effective_model_cmd is not None:
        effective_claude_cmd = effective_model_cmd.argv
    elif claude_cmd is not None:
        effective_claude_cmd = claude_cmd
    else:
        effective_model_cmd = build_model_command(Provider.CLAUDE, None)
        effective_claude_cmd = effective_model_cmd.argv

    job_id = s1_request.job_id
    company, title = s1_request.company, s1_request.title
    stage_records: list[StageRecord] = []
    total_model_calls = 0
    alignment_fingerprint: str | None = None
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
        prefix = retry_prefix or f"python -m scripts.tailor_pilot run --job-id {job_id}"
        retry_command = None
        if failed_stage is not None:
            failed_record = next((r for r in manifest.stages if r.stage == failed_stage), None)
            if failed_record and failed_record.outcome_kind == "NO_TAILORABLE_COVERAGE":
                retry_command = None
            else:
                retry_command = f"{prefix} --only {failed_stage.value}"
        return RunOutcome(manifest=manifest, failed_stage=failed_stage, retry_command=retry_command)

    # ---- PREPARE ----
    started = _now()
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
            model_command=effective_model_cmd, claude_cmd=effective_claude_cmd,
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
            model_command=effective_model_cmd, claude_cmd=effective_claude_cmd,
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
    from src.tailor.s2 import load_assumed_baseline_terms
    catalog = replace(catalog, assumed_baseline_terms=load_assumed_baseline_terms(assumed_baseline_terms_path))
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
            model_command=effective_model_cmd, claude_cmd=effective_claude_cmd,
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

    # ---- HALT CHECK (M8N-0c) ----
    if not any(entry.status == "covered" for entry in s2.coverage):
        record(Stage.S3, StageState.FAILED, "NO_TAILORABLE_COVERAGE", started=_now(),
               error="Pipeline halted: zero actionable covered terms after baseline mapping.")
        return finish(Stage.S3)

    from src.tailor.s3 import build_s3_request
    s3_request = build_s3_request(job_id, company, title, s1, s0, s2, alignment)


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
            model_command=effective_model_cmd, claude_cmd=effective_claude_cmd,
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
            model_command=effective_model_cmd, claude_cmd=effective_claude_cmd,
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
            directory=directory, reject_dir=reject_dir,
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


# ---------------------------------------------------------------------------
# Read-only pilot-job selection (spec §4). No SQL outside src/db.py:
# db.rows_by_status already issues `SELECT * FROM jobs WHERE status = ?`, so
# every column an eligibility or spread criterion needs is already there.
# ---------------------------------------------------------------------------

import hashlib

from src.db import ELIGIBLE_TAILORING_BASE_VARIANTS, PROHIBITED_TAILORING_JOB_IDS, rows_by_status
from src.models import Status

#: Criterion 4 buckets (bytes of raw jd_text).
_SHORT_JD_MAX = 3000
_MEDIUM_JD_MIN = 5000
_MEDIUM_JD_MAX = 8000
_LONG_JD_MIN = 12000

#: Criterion 5: a crude, deterministic domain-distance heuristic over the
#: job title. This profile's flagship projects are backend/data/ML work;
#: a title naming those domains is "close", everything else is "distant".
#: This is a first-pass signal for the printed reasons, not a claim of
#: semantic accuracy -- the user confirms every pick before any run.
_CLOSE_DOMAIN_TITLE_HINTS = ("ai", "machine learning", "data", "intelligent systems", "ml ")

@dataclass(frozen=True)
class PilotCandidate:
    job_id: int
    company: str
    title: str
    base_variant: str
    jd_length: int
    content_group: str
    reasons: tuple[str, ...]


def _content_group(jd_text: str) -> str:
    normalized = " ".join(jd_text.split()).casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _is_close_domain(candidate: PilotCandidate) -> bool:
    title = candidate.title.casefold()
    return any(hint in title for hint in _CLOSE_DOMAIN_TITLE_HINTS)


def eligible_candidates(conn) -> tuple[PilotCandidate, ...]:
    """Criterion 1 (spec §4): status='SHORTLISTED', jd_quality='ats',
    non-empty jd_text, base_variant in {backend, ml}, id not prohibited.
    Read-only: only db.rows_by_status, never a write."""
    candidates: list[PilotCandidate] = []
    for row in rows_by_status(conn, Status.SHORTLISTED):
        if row["id"] in PROHIBITED_TAILORING_JOB_IDS:
            continue
        if row["jd_quality"] != "ats":
            continue
        jd_text = row["jd_text"] or ""
        if not jd_text.strip():
            continue
        if row["base_variant"] not in ELIGIBLE_TAILORING_BASE_VARIANTS:
            continue
        candidates.append(PilotCandidate(
            job_id=row["id"], company=row["company"], title=row["title"],
            base_variant=row["base_variant"], jd_length=len(jd_text),
            content_group=_content_group(jd_text), reasons=(),
        ))
    return tuple(candidates)


def _jd_bucket(candidate: PilotCandidate) -> str | None:
    if candidate.jd_length < _SHORT_JD_MAX:
        return "short"
    if _MEDIUM_JD_MIN <= candidate.jd_length <= _MEDIUM_JD_MAX:
        return "medium"
    if candidate.jd_length > _LONG_JD_MIN:
        return "long"
    return None


def select_pilot_jobs(candidates: tuple[PilotCandidate, ...], count: int = 3) -> tuple[PilotCandidate, ...]:
    """Applies spec §4 criteria 2-6 in order against already-eligible
    candidates, raising ValueError naming the unmet criterion rather than
    silently returning a weaker set. Pure and deterministic: candidates are
    always considered in job_id order, so ties resolve the same way every
    time."""
    if not candidates:
        raise ValueError("no eligible candidates to select from")

    # Criterion 2: one row per distinct JD content group -- a deterministic
    # representative (lowest job_id) stands in for its whole group.
    by_group: dict[str, PilotCandidate] = {}
    for candidate in sorted(candidates, key=lambda c: c.job_id):
        by_group.setdefault(candidate.content_group, candidate)
    pool = tuple(sorted(by_group.values(), key=lambda c: c.job_id))

    if count != 3:
        # The remaining criteria are calibrated specifically for a 3-job
        # pilot (both variants, short/medium/long, domain spread, one GAP).
        # For any other count, the only guarantee this function can keep is
        # criterion 2 (no duplicate content groups).
        if len(pool) < count:
            raise ValueError(
                f"only {len(pool)} distinct-content-group candidates available, need {count}"
            )
        chosen = pool[:count]
        return tuple(
            replace(candidate, reasons=("distinct JD content group",)) for candidate in chosen
        )

    # Criterion 3: both base variants represented.
    ml_pool = [c for c in pool if c.base_variant == "ml"]
    backend_pool = [c for c in pool if c.base_variant == "backend"]
    if not ml_pool:
        raise ValueError("cannot satisfy criterion: both base variants represented (no eligible 'ml' candidate)")
    if not backend_pool:
        raise ValueError("cannot satisfy criterion: both base variants represented (no eligible 'backend' candidate)")

    # Criterion 4: JD length spread -- short (<3KB), medium (5-8KB), long (>12KB).
    short_pool = [c for c in pool if _jd_bucket(c) == "short"]
    medium_pool = [c for c in pool if _jd_bucket(c) == "medium"]
    long_pool = [c for c in pool if _jd_bucket(c) == "long"]
    if not short_pool:
        raise ValueError("cannot satisfy criterion: JD length spread (no short <3KB candidate)")
    if not medium_pool:
        raise ValueError("cannot satisfy criterion: JD length spread (no medium 5-8KB candidate)")
    if not long_pool:
        raise ValueError("cannot satisfy criterion: JD length spread (no long >12KB candidate)")

    reasons: dict[int, list[str]] = {}

    def _add_reason(candidate: PilotCandidate, reason: str) -> None:
        reasons.setdefault(candidate.job_id, []).append(reason)

    # Prefer a long candidate that is also 'ml', covering criteria 3 and 4
    # with a single pick when the corpus allows it.
    long_ml = [c for c in long_pool if c.base_variant == "ml"]
    long_pick = long_ml[0] if long_ml else long_pool[0]
    picks: list[PilotCandidate] = [long_pick]
    _add_reason(long_pick, f"long JD ({long_pick.jd_length} bytes, >{_LONG_JD_MIN})")
    if long_pick.base_variant == "ml":
        _add_reason(long_pick, "provides the required 'ml' base_variant")

    if not any(c.base_variant == "ml" for c in picks):
        ml_pick = ml_pool[0]
        picks.append(ml_pick)
        _add_reason(ml_pick, "provides the required 'ml' base_variant")

    picked_ids = {c.job_id for c in picks}
    for bucket, label in ((short_pool, f"short JD (<{_SHORT_JD_MAX})"), (medium_pool, f"medium JD ({_MEDIUM_JD_MIN}-{_MEDIUM_JD_MAX})")):
        candidate = next((c for c in bucket if c.job_id not in picked_ids), None)
        if candidate is None:
            raise ValueError("cannot satisfy criterion: JD length spread (no distinct candidate left for a bucket)")
        picks.append(candidate)
        picked_ids.add(candidate.job_id)
        _add_reason(candidate, f"{label}: {candidate.jd_length} bytes")

    picks.sort(key=lambda c: c.job_id)
    remaining = [c for c in pool if c.job_id not in picked_ids]
    while len(picks) < count:
        if not remaining:
            raise ValueError("cannot satisfy the requested candidate count from the eligible pool")
        filler = remaining.pop(0)
        picks.append(filler)
        picked_ids.add(filler.job_id)
        _add_reason(filler, "fills the requested candidate count")
    picks = picks[:count]

    # Criterion 5: domain distance spread -- at least one close, one distant.
    # The design (spec §4.5) treats this as a signal the operator surfaces
    # for human judgment at select-time ("these are illustrations, not a
    # commitment" -- §4), not a hard-fail gate like criteria 2-4: a job
    # title alone cannot definitively prove domain distance the way a byte
    # count or a base_variant column can. select_pilot_jobs swaps toward a
    # spread when the pool offers one, and always records which side of the
    # spread each pick landed on, but does not raise when the corpus (or a
    # synthetic candidate set) cannot supply both sides.
    if picks and not any(_is_close_domain(c) for c in picks):
        replacement = next((c for c in remaining if _is_close_domain(c)), None)
        if replacement is not None:
            swap_out = next(c for c in reversed(picks) if len(reasons.get(c.job_id, [])) <= 1)
            picks = [replacement if c.job_id == swap_out.job_id else c for c in picks]
            _add_reason(replacement, "close domain (profile-adjacent) -- satisfies domain distance spread")
    elif picks and not any(not _is_close_domain(c) for c in picks):
        replacement = next((c for c in remaining if not _is_close_domain(c)), None)
        if replacement is not None:
            swap_out = next(c for c in reversed(picks) if len(reasons.get(c.job_id, [])) <= 1)
            picks = [replacement if c.job_id == swap_out.job_id else c for c in picks]
            _add_reason(replacement, "distant domain -- satisfies domain distance spread")
    for candidate in picks:
        if not any("domain" in r for r in reasons.get(candidate.job_id, ())):
            _add_reason(candidate, "close domain" if _is_close_domain(candidate) else "distant domain")

    # Criterion 6: at least one job expected to produce a GAP. `jd_text` is
    # not carried on PilotCandidate, so a GAP-expected pick is identified by
    # base_variant == "ml" -- the only base variant whose canonical bullets
    # are silent on the profile's do_not_claim term, making an ml-variant
    # JD that demands it (e.g. "kubernetes") the natural GAP case. Any ml
    # pick already in the selection satisfies this without a swap.
    if not any(c.base_variant == "ml" for c in picks):
        raise ValueError("cannot satisfy criterion: at least one job expected to produce a GAP")
    for candidate in picks:
        if candidate.base_variant == "ml":
            _add_reason(candidate, "ml base_variant against this JD is expected to surface a GAP")

    picks.sort(key=lambda c: c.job_id)
    return tuple(replace(candidate, reasons=tuple(reasons.get(candidate.job_id, ("selected",)))) for candidate in picks)


# ---------------------------------------------------------------------------
# Cost accounting and the acceptance gate (spec §3.5, §6). Read-only: every
# figure here is aggregated from artifacts a run already wrote to disk --
# a completed run_manifest.json, render_result.json, and feedback records --
# never from re-invoking a stage.
# ---------------------------------------------------------------------------

import math


@dataclass(frozen=True)
class CostReport:
    applications: int
    total_model_calls: int
    calls_by_stage: tuple[tuple[str, int], ...]
    mean_calls_per_application: float
    g2_round_distribution: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class GateCondition:
    name: str
    threshold: str
    observed: str
    passed: bool


@dataclass(frozen=True)
class GateReport:
    conditions: tuple[GateCondition, ...]
    passed: bool


def _discover_run_manifests(root: Path) -> tuple[tuple[Path, RunManifest], ...]:
    """Every application's own persisted run_manifest.json under `root`,
    read purely as a completed run's report of what happened. This is not
    the live skip/conflict authority Task 1 warns against trusting --
    reporting on a finished run has nothing left to re-derive against. A
    directory whose manifest is missing or unparseable is silently excluded
    rather than crashing the report."""
    found: list[tuple[Path, RunManifest]] = []
    for manifest_path in sorted(Path(root).rglob("run_manifest.json")):
        raw = _read_json_or_none(manifest_path)
        if raw is None:
            continue
        try:
            manifest = manifest_from_dict(raw)
        except (PilotManifestError, KeyError, TypeError, ValueError):
            continue
        found.append((manifest_path.parent, manifest))
    return tuple(found)


def _stage_record_for(manifest: RunManifest, stage: Stage) -> StageRecord | None:
    return next((record for record in manifest.stages if record.stage == stage), None)


def cost_report(root: Path = APPLICATIONS_ROOT) -> CostReport:
    runs = _discover_run_manifests(root)
    applications = len(runs)
    total_model_calls = sum(manifest.total_model_calls for _, manifest in runs)

    calls_by_stage_totals: dict[str, int] = {}
    for _, manifest in runs:
        for record in manifest.stages:
            calls_by_stage_totals[record.stage.value] = (
                calls_by_stage_totals.get(record.stage.value, 0) + record.model_calls
            )
    calls_by_stage = tuple(sorted(calls_by_stage_totals.items()))
    mean_calls_per_application = (total_model_calls / applications) if applications else 0.0

    round_counts: dict[int, int] = {}
    for directory, _ in runs:
        raw_bundle = _read_json_or_none(directory / STAGE_ARTIFACT[Stage.G2])
        if raw_bundle is None:
            continue
        try:
            bundle = parse_g2_bundle(raw_bundle)
        except (KeyError, TypeError, ValueError):
            continue
        round_counts[bundle.rounds_used] = round_counts.get(bundle.rounds_used, 0) + 1
    g2_round_distribution = tuple(sorted(round_counts.items()))

    return CostReport(
        applications=applications, total_model_calls=total_model_calls, calls_by_stage=calls_by_stage,
        mean_calls_per_application=mean_calls_per_application, g2_round_distribution=g2_round_distribution,
    )


def acceptance_gate(
    root: Path = APPLICATIONS_ROOT,
    feedback_dir: Path = Path("data/feedback"),
    expected_runs: int = 3,
) -> GateReport:
    """The seven minimum conditions from design §6 for the user to consider
    scaling past the pilot, each reporting its own threshold and observed
    value. Failing any of them means fix and re-run the three, not proceed
    with a caveat -- so `passed` is a strict conjunction, and no condition
    is skipped just because an earlier one already failed."""
    runs = _discover_run_manifests(root)
    conditions: list[GateCondition] = []

    reached_packet = sum(
        1 for _, manifest in runs
        if (record := _stage_record_for(manifest, Stage.G3)) is not None
        and record.state in (StageState.COMPLETE, StageState.SKIPPED_COMPLETE)
    )
    conditions.append(GateCondition(
        name="runs_reaching_packet",
        threshold=f"{expected_runs} of {expected_runs}",
        observed=f"{reached_packet} of {len(runs)}",
        passed=len(runs) == expected_runs and reached_packet == expected_runs,
    ))

    l7_failure_total = 0
    for directory, _ in runs:
        raw_render = _read_json_or_none(directory / STAGE_ARTIFACT[Stage.RENDER])
        if raw_render is None:
            continue
        try:
            render_result = parse_render_result(raw_render)
        except (KeyError, TypeError, ValueError):
            continue
        l7_failure_total += len(render_result.l7_violations)
    conditions.append(GateCondition(
        name="l7_failures", threshold="0", observed=str(l7_failure_total), passed=l7_failure_total == 0,
    ))

    # The feedback index's own "latest revision per (job_id, fingerprint)"
    # dedup rule (feedback.py's store_feedback / summarize_feedback) is
    # re-applied here rather than exposed as a public helper there, so
    # unsupported_claims -- the one figure summarize_feedback does not
    # already aggregate -- is counted over the exact same record set the
    # rest of this gate uses.
    entries = load_feedback_index(feedback_dir)
    latest_by_key: dict[tuple[object, object], dict[str, object]] = {}
    for entry in entries:
        key = (entry["job_id"], entry["alignment_fingerprint"])
        current = latest_by_key.get(key)
        if current is None or entry["revision"] > current["revision"]:
            latest_by_key[key] = entry
    records = [
        parse_feedback_record(json.loads(Path(entry["path"]).read_text(encoding="utf-8")))
        for entry in latest_by_key.values()
    ]
    unsupported_total = sum(len(record.unsupported_claims) for record in records)
    conditions.append(GateCondition(
        name="unsupported_claims", threshold="0", observed=str(unsupported_total),
        passed=unsupported_total == 0,
    ))

    summary = summarize_feedback(feedback_dir)
    min_would_submit_yes = math.ceil(2 * expected_runs / 3)
    conditions.append(GateCondition(
        name="would_submit_yes",
        threshold=f">= {min_would_submit_yes} of {expected_runs}",
        observed=f"{summary.would_submit_yes} of {summary.total}",
        passed=summary.would_submit_yes >= min_would_submit_yes,
    ))

    max_needs_revision = expected_runs // 3
    conditions.append(GateCondition(
        name="needs_another_revision",
        threshold=f"<= {max_needs_revision} of {expected_runs}",
        observed=f"{summary.needs_revision} of {summary.total}",
        passed=summary.needs_revision <= max_needs_revision,
    ))

    conditions.append(GateCondition(
        name="mean_visual_quality", threshold=">= 2.0",
        observed=f"{summary.mean_visual_quality:.2f}", passed=summary.mean_visual_quality >= 2.0,
    ))

    conditions.append(GateCondition(
        name="mean_company_alignment", threshold=">= 2.0",
        observed=f"{summary.mean_company_alignment:.2f}", passed=summary.mean_company_alignment >= 2.0,
    ))

    return GateReport(conditions=tuple(conditions), passed=all(condition.passed for condition in conditions))
