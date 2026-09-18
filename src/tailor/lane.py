"""Apply-Now lane (M8N-0, multi-provider): a file-fed entry to the validated
tailoring chain. Reads a pasted JD, never opens data/jobs.db, and delegates every
stage to src.tailor.pilot.run_stages. Supports claude, gemini, and codex providers."""
from __future__ import annotations

import datetime
import hashlib
import json
import logging
import shutil
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
from src.tailor.providers import (
    Provider,
    build_model_command,
    check_gemini_credentials,
    check_openai_credentials,
)
from src.tailor.publish import application_dir, slugify
from src.tailor.s1 import S1Request

log = logging.getLogger(__name__)

LANE_MANIFEST_SCHEMA_V1 = "m8n0.lane_manifest.v1"
LANE_MANIFEST_SCHEMA = "m8n0.lane_manifest.v2"
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
    try:
        return build_model_command(Provider.CLAUDE, model).argv
    except ValueError as exc:
        raise LaneError(str(exc)) from exc


def lane_directory(root: Path, company: str, title: str, suffix: str | None = None, provider: str = "claude") -> Path:
    base = application_dir(root, company, title)
    prov_str = provider.value if isinstance(provider, Provider) else str(provider)
    is_non_claude = bool(prov_str and prov_str.lower() != Provider.CLAUDE.value)

    if suffix is not None and suffix.strip():
        user_suffix = slugify(suffix)
        if is_non_claude:
            return base.with_name(f"{base.name}-{user_suffix}-{prov_str.lower()}")
        return base.with_name(f"{base.name}-{user_suffix}")
    if is_non_claude:
        return base.with_name(f"{base.name}-{prov_str.lower()}")
    return base


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
    provider: str = "claude"
    provenance_fingerprint: str = ""
    source_url: str = ""
    ats_url: str | None = None
    attestation_digest: str | None = None


_LANE_MANIFEST_V1_KEYS = {
    "schema_version", "job_id", "jd_sha256", "jd_path", "company", "title", "variant", "model",
    "claude_cmd", "jd_quality", "created_at",
}
_LANE_MANIFEST_V1_PLUS_PROVIDER_KEYS = _LANE_MANIFEST_V1_KEYS | {"provider"}
_LANE_MANIFEST_V2_KEYS = {
    "schema_version", "job_id", "jd_sha256", "jd_path", "company", "title", "variant", "model",
    "claude_cmd", "jd_quality", "created_at", "provider", "provenance_fingerprint", "source_url",
    "ats_url", "attestation_digest",
}


def lane_manifest_to_dict(m: LaneManifest) -> dict[str, object]:
    return {
        "schema_version": m.schema_version,
        "job_id": m.job_id,
        "jd_sha256": m.jd_sha256,
        "jd_path": m.jd_path,
        "company": m.company,
        "title": m.title,
        "variant": m.variant,
        "model": m.model,
        "claude_cmd": list(m.claude_cmd),
        "jd_quality": m.jd_quality,
        "created_at": m.created_at,
        "provider": m.provider,
        "provenance_fingerprint": m.provenance_fingerprint,
        "source_url": m.source_url,
        "ats_url": m.ats_url,
        "attestation_digest": m.attestation_digest,
    }


def parse_lane_manifest(raw: object) -> LaneManifest:
    if not isinstance(raw, dict):
        raise LaneError("lane_manifest.json: expected a JSON object")

    schema = raw.get("schema_version")
    if schema == LANE_MANIFEST_SCHEMA_V1:
        raise LaneError(
            "lane_manifest.json has legacy schema v1 lacking provenance fingerprint binding; "
            "refusing unverified directory. Use --suffix or remove the application directory to re-run."
        )
    if schema != LANE_MANIFEST_SCHEMA:
        raise LaneError(f"lane_manifest.json: unsupported schema {schema!r}")

    if set(raw.keys()) != _LANE_MANIFEST_V2_KEYS:
        missing = _LANE_MANIFEST_V2_KEYS - set(raw.keys())
        extra = set(raw.keys()) - _LANE_MANIFEST_V2_KEYS
        raise LaneError(
            f"lane_manifest.json: unexpected schema fields (missing: {sorted(missing)}, extra: {sorted(extra)})"
        )

    if isinstance(raw["job_id"], bool) or not isinstance(raw["job_id"], int):
        raise LaneError("lane_manifest.json: job_id must be an integer")
    if not isinstance(raw["claude_cmd"], list) or not all(isinstance(x, str) for x in raw["claude_cmd"]):
        raise LaneError("lane_manifest.json: claude_cmd must be a list of strings")
    if raw["model"] is not None and not isinstance(raw["model"], str):
        raise LaneError("lane_manifest.json: model must be a string or null")
    if raw["ats_url"] is not None and not isinstance(raw["ats_url"], str):
        raise LaneError("lane_manifest.json: ats_url must be a string or null")
    if raw["attestation_digest"] is not None and not isinstance(raw["attestation_digest"], str):
        raise LaneError("lane_manifest.json: attestation_digest must be a string or null")

    for key in (
        "jd_sha256", "jd_path", "company", "title", "variant", "jd_quality", "created_at",
        "provider", "provenance_fingerprint", "source_url",
    ):
        if not isinstance(raw[key], str) or not raw[key]:
            raise LaneError(f"lane_manifest.json: {key} must be a nonempty string")

    return LaneManifest(
        schema_version=raw["schema_version"],
        job_id=raw["job_id"],
        jd_sha256=raw["jd_sha256"],
        jd_path=raw["jd_path"],
        company=raw["company"],
        title=raw["title"],
        variant=raw["variant"],
        model=raw["model"],
        claude_cmd=tuple(raw["claude_cmd"]),
        jd_quality=raw["jd_quality"],
        created_at=raw["created_at"],
        provider=raw["provider"],
        provenance_fingerprint=raw["provenance_fingerprint"],
        source_url=raw["source_url"],
        ats_url=raw["ats_url"],
        attestation_digest=raw["attestation_digest"],
    )


def _preflight_findings(profile_path: Path, template_path: Path, prompt_dir: Path) -> tuple[PreflightFinding, ...]:
    with tempfile.TemporaryDirectory(prefix="apply-now-preflight-") as workdir:
        report = run_preflight(Path(profile_path), Path(template_path), Path(prompt_dir), Path(workdir), skip_render=True)
    return report.findings


def _manifest_mismatch(
    existing: LaneManifest,
    *,
    jd_sha256: str,
    provenance_fingerprint: str,
    company: str,
    title: str,
    variant: str,
    provider: str = "claude",
    jd_quality: str = "ats",
    job_id: int,
    source_url: str,
    ats_url: str | None = None,
    attestation_digest: str | None = None,
) -> str | None:
    if existing.jd_sha256 != jd_sha256:
        return "jd text differs from the JD this directory was created from"
    if existing.provenance_fingerprint != provenance_fingerprint:
        return "provenance fingerprint differs from this directory's lane manifest"
    if (existing.company, existing.title) != (company, title):
        return "company/title differ from this directory's lane manifest"
    if existing.variant != variant:
        return f"variant {variant!r} differs from this directory's variant {existing.variant!r}"
    if existing.provider != provider:
        return f"provider {provider!r} differs from this directory's provider {existing.provider!r}"
    if existing.jd_quality != jd_quality:
        return f"jd_quality {jd_quality!r} differs from this directory's jd_quality {existing.jd_quality!r}"
    if existing.job_id != job_id:
        return f"job_id {job_id} differs from this directory's job_id {existing.job_id}"
    if existing.source_url != source_url:
        return f"source_url {source_url!r} differs from this directory's source_url {existing.source_url!r}"
    if existing.ats_url != ats_url:
        return f"ats_url {ats_url!r} differs from this directory's ats_url {existing.ats_url!r}"
    if existing.attestation_digest != attestation_digest:
        return "attestation metadata differs from this directory's lane manifest"
    return None




def run_manual_application(
    jd_path: Path, *, company: str, title: str, variant: str,
    root: Path = APPLICATIONS_MANUAL_ROOT,
    provider: str | Provider = Provider.CLAUDE,
    model: str | None = None,
    suffix: str | None = None,
    profile_path: Path = Path("config/master_profile.yaml"),
    template_path: Path = Path("profile/template.tex"),
    banned_words_path: Path = Path("config/banned_words.txt"),
    assumed_baseline_terms_path: Path = Path("config/assumed_baseline_terms.txt"),
    taste_path: Path = Path("config/taste.md"),
    trace_dir: Path = Path("data/traces"),
    prompt_dir: Path = DEFAULT_PROMPT_DIR,
    stop_after: Stage | None = None, only: Stage | None = None, dry_run: bool = False,
    db_path: Path | str | None = None,
    sidecar_path: Path | str | None = None,
) -> RunOutcome:
    started = _now()
    jd_path = Path(jd_path)
    if not jd_path.is_file():
        raise LaneError(f"JD file not found: {jd_path}")

    # Validate provenance boundary: strict sidecar or manifest contract
    from src.tailor.provenance import (
        ProvenanceError,
        validate_provenance_for_tailoring,
    )

    db_conn = None
    if db_path is not None:
        db_p = Path(db_path)
        if db_p.is_file():
            from src import db as db_module
            db_conn = db_module.get_readonly_connection(db_p)
    elif Path("data/jobs.db").is_file():
        from src import db as db_module
        try:
            db_conn = db_module.get_readonly_connection("data/jobs.db")
        except Exception:
            db_conn = None

    try:
        provenance = validate_provenance_for_tailoring(
            jd_path,
            company=company,
            title=title,
            db_conn=db_conn,
            sidecar_path=sidecar_path,
        )
    except ProvenanceError as exc:
        raise LaneError(str(exc)) from exc
    finally:
        if db_conn is not None:
            db_conn.close()

    jd_text = normalize_jd(jd_path.read_text(encoding="utf-8"))

    if isinstance(provider, str):
        try:
            prov_enum = Provider(provider.lower())
        except ValueError:
            raise LaneError(f"unknown provider {provider!r}; expected one of {[p.value for p in Provider]}")
    else:
        prov_enum = provider

    try:
        model_command = build_model_command(prov_enum, model)
    except ValueError as exc:
        raise LaneError(str(exc)) from exc

    profile = load_profile(profile_path)
    if variant not in profile.base_variants:
        raise LaneError(f"unknown base variant {variant!r}; expected one of {sorted(profile.base_variants)}")

    job_id = lane_job_id(jd_text)
    jd_sha256 = _jd_sha256(jd_text)
    directory = lane_directory(Path(root), company, title, suffix=suffix, provider=prov_enum.value)
    retry_prefix = (
        f"python -m scripts.tailor_now run --jd {jd_path} --company {company!r} --title {title!r} --variant {variant}"
        + (f" --provider {prov_enum.value}" if prov_enum is not Provider.CLAUDE else "")
        + (f" --suffix {suffix!r}" if suffix else "") + (f" --model {model}" if model else "")
    )

    from src.tailor.provenance import (
        compute_provenance_fingerprint,
        parse_provenance_dict,
    )

    manifest_path = directory / LANE_MANIFEST_NAME
    prov_fingerprint = compute_provenance_fingerprint(provenance)
    att_digest = (
        hashlib.sha256(json.dumps(provenance.attestation.to_dict(), sort_keys=True).encode("utf-8")).hexdigest()
        if provenance.attestation is not None else None
    )

    if manifest_path.exists():
        try:
            existing = parse_lane_manifest(json.loads(manifest_path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            return _prepare_failure(job_id, "lane_manifest_unreadable", str(exc), started)
        reason = _manifest_mismatch(
            existing,
            jd_sha256=jd_sha256,
            provenance_fingerprint=prov_fingerprint,
            company=company,
            title=title,
            variant=variant,
            provider=prov_enum.value,
            jd_quality=provenance.jd_quality,
            job_id=existing.job_id,
            source_url=provenance.source_url,
            ats_url=provenance.ats_url,
            attestation_digest=att_digest,
        )
        if reason is not None:
            return _prepare_failure(
                job_id, "lane_manifest_mismatch",
                f"{reason}; use --suffix for a different posting or remove {directory} by hand", started,
            )
        job_id = existing.job_id

    sidecar_snapshot = directory / "jd.provenance.json"
    if sidecar_snapshot.exists():
        try:
            snap_raw = json.loads(sidecar_snapshot.read_text(encoding="utf-8"))
            snap_prov = parse_provenance_dict(snap_raw)
            if compute_provenance_fingerprint(snap_prov) != prov_fingerprint:
                return _prepare_failure(
                    job_id, "lane_manifest_mismatch",
                    f"existing jd.provenance.json in {directory} differs from supplied provenance; "
                    f"refusing to silently overwrite snapshot. Use --suffix or remove the directory",
                    started,
                )
        except Exception as exc:
            return _prepare_failure(job_id, "lane_manifest_unreadable", str(exc), started)

    # Preflight provider requirements before any model call (dry-run does no model call)
    if not dry_run:
        if prov_enum is Provider.CLAUDE:
            exe = model_command.argv[0] if model_command.argv else "claude"
            if shutil.which(exe) is None:
                return _prepare_failure(
                    job_id, "preflight_failure",
                    f"provider executable {exe!r} not found on PATH", started,
                )
        elif prov_enum is Provider.OPENAI:
            cred_err = check_openai_credentials()
            if cred_err is not None:
                return _prepare_failure(job_id, "preflight_failure", cred_err, started)
        elif prov_enum is Provider.GEMINI:
            cred_err = check_gemini_credentials()
            if cred_err is not None:
                return _prepare_failure(job_id, "preflight_failure", cred_err, started)

    findings = _preflight_findings(profile_path, template_path, prompt_dir)
    if findings:
        joined = "; ".join(f"{f.surface}: {f.message}" for f in findings)
        return _prepare_failure(job_id, "preflight_failure", joined, started)

    s1_request = S1Request(
        job_id=job_id,
        company=company,
        title=title,
        jd_text=jd_text,
        jd_quality=provenance.jd_quality,
    )

    if not dry_run:
        directory.mkdir(parents=True, exist_ok=True)
        snapshot = directory / JD_SNAPSHOT_NAME
        if not snapshot.exists():
            snapshot.write_text(jd_text, encoding="utf-8")
        if not sidecar_snapshot.exists():
            write_json_atomic(sidecar_snapshot, provenance.to_dict())
        if not manifest_path.exists():
            write_json_atomic(manifest_path, lane_manifest_to_dict(LaneManifest(
                schema_version=LANE_MANIFEST_SCHEMA, job_id=job_id, jd_sha256=jd_sha256, jd_path=str(jd_path),
                company=company, title=title, variant=variant, model=model, claude_cmd=model_command.argv,
                jd_quality=provenance.jd_quality, created_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                provider=prov_enum.value, provenance_fingerprint=prov_fingerprint,
                source_url=provenance.source_url, ats_url=provenance.ats_url, attestation_digest=att_digest,
            )))
        log.info("apply-now lane: job %d (%s / %s) -> %s", job_id, company, title, directory)

    return run_stages(
        s1_request, variant, directory=directory, profile_path=profile_path, root=Path(root),
        template_path=template_path, banned_words_path=banned_words_path, taste_path=taste_path,
        assumed_baseline_terms_path=assumed_baseline_terms_path,
        trace_dir=trace_dir, prompt_dir=prompt_dir, stop_after=stop_after, only=only, dry_run=dry_run,
        model_command=model_command, claude_cmd=model_command.argv,
        reject_dir=directory / "rejected", retry_prefix=retry_prefix,
    )
