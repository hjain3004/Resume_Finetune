"""Apply-Now lane (M8N-0): a file-fed entry to the validated tailoring
chain. Reads a pasted JD, never opens data/jobs.db, and delegates every
stage to src.tailor.pilot.run_stages. Spec:
docs/superpowers/specs/2026-09-01-m8n-apply-now-lane-design.md §7."""
from __future__ import annotations

import datetime
import hashlib
import json
import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path

from src.profile import load_profile
from src.tailor.artifacts import write_json_atomic
from src.tailor.invoke import DEFAULT_CLAUDE_CMD
from src.tailor.pilot import (
    DEFAULT_PROMPT_DIR,
    RunOutcome,
    Stage,
    _now,
    _prepare_failure,
    run_stages,
)
from src.tailor.preflight import PreflightFinding, run_preflight
from src.tailor.publish import application_dir, slugify
from src.tailor.s1 import S1Request

log = logging.getLogger(__name__)

LANE_MANIFEST_SCHEMA = "m8n0.lane_manifest.v1"
APPLICATIONS_MANUAL_ROOT = Path("applications_manual")
JD_MIN_CHARS = 300
JD_MAX_CHARS = 40_000
LANE_MANIFEST_NAME = "lane_manifest.json"
JD_SNAPSHOT_NAME = "jd.txt"


class LaneError(ValueError):
    """Operator input the lane refuses (bad JD, unknown variant, bad model name)."""


def normalize_jd(raw: str) -> str:
    text = raw[1:] if raw.startswith("﻿") else raw
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if len(text) < JD_MIN_CHARS:
        raise LaneError(f"jd text must be at least {JD_MIN_CHARS} characters, got {len(text)}")
    if len(text) > JD_MAX_CHARS:
        raise LaneError(f"jd text must be at most {JD_MAX_CHARS} characters, got {len(text)}")
    return text


def _jd_sha256(jd_text: str) -> str:
    return hashlib.sha256(jd_text.encode("utf-8")).hexdigest()


def lane_job_id(jd_text: str) -> int:
    """Negative, deterministic, content-bound (spec §7.7). Negative ids cannot
    collide with DB ids and mark every artifact as lane-issued."""
    return -(int(_jd_sha256(jd_text)[:12], 16) % 10**9) - 1


def build_claude_cmd(model: str | None) -> tuple[str, ...]:
    """`--tools ""` must never be last and the trailing `--` keeps the prompt
    positional (see src/tailor/invoke.py)."""
    if model is None:
        return DEFAULT_CLAUDE_CMD
    if not model.strip() or model.startswith("-") or any(ch.isspace() for ch in model):
        raise LaneError(f"model must be a bare model name, got {model!r}")
    return ("claude", "-p", "--model", model, "--tools", "", "--no-session-persistence", "--")


def lane_directory(root: Path, company: str, title: str, suffix: str | None) -> Path:
    base = application_dir(root, company, title)
    if suffix is None or not suffix.strip():
        return base
    return base.with_name(f"{base.name}-{slugify(suffix)}")


@dataclass(frozen=True)
class LaneManifest:
    schema_version: str
    job_id: int
    jd_sha256: str
    jd_path: str
    company: str
    title: str
    variant: str
    model: str | None
    claude_cmd: tuple[str, ...]
    jd_quality: str
    created_at: str


_LANE_MANIFEST_KEYS = {
    "schema_version", "job_id", "jd_sha256", "jd_path", "company", "title", "variant", "model",
    "claude_cmd", "jd_quality", "created_at",
}


def lane_manifest_to_dict(m: LaneManifest) -> dict[str, object]:
    return {
        "schema_version": m.schema_version, "job_id": m.job_id, "jd_sha256": m.jd_sha256,
        "jd_path": m.jd_path, "company": m.company, "title": m.title, "variant": m.variant,
        "model": m.model, "claude_cmd": list(m.claude_cmd), "jd_quality": m.jd_quality,
        "created_at": m.created_at,
    }


def parse_lane_manifest(raw: object) -> LaneManifest:
    if not isinstance(raw, dict) or set(raw) != _LANE_MANIFEST_KEYS:
        raise LaneError("lane_manifest.json: unexpected or missing fields")
    if raw["schema_version"] != LANE_MANIFEST_SCHEMA:
        raise LaneError(f"lane_manifest.json: unsupported schema {raw['schema_version']!r}")
    if isinstance(raw["job_id"], bool) or not isinstance(raw["job_id"], int):
        raise LaneError("lane_manifest.json: job_id must be an integer")
    if not isinstance(raw["claude_cmd"], list) or not all(isinstance(x, str) for x in raw["claude_cmd"]):
        raise LaneError("lane_manifest.json: claude_cmd must be a list of strings")
    if raw["model"] is not None and not isinstance(raw["model"], str):
        raise LaneError("lane_manifest.json: model must be a string or null")
    for key in ("jd_sha256", "jd_path", "company", "title", "variant", "jd_quality", "created_at"):
        if not isinstance(raw[key], str) or not raw[key]:
            raise LaneError(f"lane_manifest.json: {key} must be a nonempty string")
    return LaneManifest(
        schema_version=raw["schema_version"], job_id=raw["job_id"], jd_sha256=raw["jd_sha256"],
        jd_path=raw["jd_path"], company=raw["company"], title=raw["title"], variant=raw["variant"],
        model=raw["model"], claude_cmd=tuple(raw["claude_cmd"]), jd_quality=raw["jd_quality"],
        created_at=raw["created_at"],
    )


def _preflight_findings(profile_path: Path, template_path: Path, prompt_dir: Path) -> tuple[PreflightFinding, ...]:
    with tempfile.TemporaryDirectory(prefix="apply-now-preflight-") as workdir:
        report = run_preflight(Path(profile_path), Path(template_path), Path(prompt_dir), Path(workdir), skip_render=True)
    return report.findings


def _manifest_mismatch(existing: LaneManifest, *, jd_sha256: str, company: str, title: str, variant: str) -> str | None:
    if existing.jd_sha256 != jd_sha256:
        return "jd text differs from the JD this directory was created from"
    if (existing.company, existing.title) != (company, title):
        return "company/title differ from this directory's lane manifest"
    if existing.variant != variant:
        return f"variant {variant!r} differs from this directory's variant {existing.variant!r}"
    return None


def run_manual_application(
    jd_path: Path, *, company: str, title: str, variant: str,
    root: Path = APPLICATIONS_MANUAL_ROOT, model: str | None = None, suffix: str | None = None,
    profile_path: Path = Path("config/master_profile.yaml"),
    template_path: Path = Path("profile/template.tex"),
    banned_words_path: Path = Path("config/banned_words.txt"),
    assumed_baseline_terms_path: Path = Path("config/assumed_baseline_terms.txt"),
    taste_path: Path = Path("config/taste.md"),
    trace_dir: Path = Path("data/traces"),
    prompt_dir: Path = DEFAULT_PROMPT_DIR,
    stop_after: Stage | None = None, only: Stage | None = None, dry_run: bool = False,
) -> RunOutcome:
    started = _now()
    jd_path = Path(jd_path)
    jd_text = normalize_jd(jd_path.read_text(encoding="utf-8"))
    claude_cmd = build_claude_cmd(model)
    profile = load_profile(profile_path)
    if variant not in profile.base_variants:
        raise LaneError(f"unknown base variant {variant!r}; expected one of {sorted(profile.base_variants)}")

    job_id = lane_job_id(jd_text)
    jd_sha256 = _jd_sha256(jd_text)
    directory = lane_directory(Path(root), company, title, suffix)
    retry_prefix = (
        f"python -m scripts.tailor_now run --jd {jd_path} --company {company!r} --title {title!r} --variant {variant}"
        + (f" --suffix {suffix!r}" if suffix else "") + (f" --model {model}" if model else "")
    )

    manifest_path = directory / LANE_MANIFEST_NAME
    if manifest_path.exists():
        try:
            existing = parse_lane_manifest(json.loads(manifest_path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            return _prepare_failure(job_id, "lane_manifest_unreadable", str(exc), started)
        reason = _manifest_mismatch(existing, jd_sha256=jd_sha256, company=company, title=title, variant=variant)
        if reason is not None:
            return _prepare_failure(
                job_id, "lane_manifest_mismatch",
                f"{reason}; use --suffix for a different posting or remove {directory} by hand", started,
            )
        job_id = existing.job_id

    findings = _preflight_findings(profile_path, template_path, prompt_dir)
    if findings:
        joined = "; ".join(f"{f.surface}: {f.message}" for f in findings)
        return _prepare_failure(job_id, "preflight_failure", joined, started)

    s1_request = S1Request(job_id=job_id, company=company, title=title, jd_text=jd_text, jd_quality="ats")

    if not dry_run:
        directory.mkdir(parents=True, exist_ok=True)
        snapshot = directory / JD_SNAPSHOT_NAME
        if not snapshot.exists():
            snapshot.write_text(jd_text, encoding="utf-8")
        if not manifest_path.exists():
            write_json_atomic(manifest_path, lane_manifest_to_dict(LaneManifest(
                schema_version=LANE_MANIFEST_SCHEMA, job_id=job_id, jd_sha256=jd_sha256, jd_path=str(jd_path),
                company=company, title=title, variant=variant, model=model, claude_cmd=claude_cmd,
                jd_quality="ats", created_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            )))
        log.info("apply-now lane: job %d (%s / %s) -> %s", job_id, company, title, directory)

    return run_stages(
        s1_request, variant, directory=directory, profile_path=profile_path, root=Path(root),
        template_path=template_path, banned_words_path=banned_words_path, taste_path=taste_path,
        assumed_baseline_terms_path=assumed_baseline_terms_path,
        trace_dir=trace_dir, prompt_dir=prompt_dir, stop_after=stop_after, only=only, dry_run=dry_run,
        claude_cmd=claude_cmd, reject_dir=directory / "rejected", retry_prefix=retry_prefix,
    )
