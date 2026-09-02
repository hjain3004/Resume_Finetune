"""Atomic per-application publication: render an accepted TailoredDraft
through the LaTeX arm, verify it with the tailored L7 aggregate, and publish
fail-closed and idempotently. Rendering happens in a temporary directory;
only a VALID outcome copies anything into the application directory, and
render_result.json is written last as the commit marker."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from src.render.l7 import run_l7_tailored
from src.render.latex import render_latex
from src.render.lines import locate_text_lines, parse_rendered_lines
from src.render.parse import parse_pdf
from src.render.tailored import TailoredRenderError, modified_bullet_ids, render_doc_from_draft
from src.tailor.artifacts import write_json_atomic

RENDER_RESULT_SCHEMA = "m8p5.render_result.v1"


class RenderOutcomeKind(str, Enum):
    FINGERPRINT_MISMATCH = "fingerprint_mismatch"
    MAPPING_FAILURE = "mapping_failure"
    RENDERER_UNAVAILABLE = "renderer_unavailable"
    RENDERER_FAILURE = "renderer_failure"
    PARSE_FAILURE = "parse_failure"
    L7_FAILURE = "l7_failure"
    ALREADY_PUBLISHED = "already_published"
    CONFLICT = "conflict"
    VALID = "valid"


@dataclass(frozen=True)
class RenderResult:
    schema_version: str
    job_id: int
    company: str
    title: str
    alignment_fingerprint: str
    s3_bundle_schema_version: str
    source_path: str
    pdf_path: str
    pdf_sha256: str
    page_count: int
    size_bytes: int
    modified_bullet_ids: tuple[str, ...]
    modified_bullet_line_counts: tuple[tuple[str, int], ...]
    l7_violations: tuple[str, ...]
    render_line_check: str


@dataclass(frozen=True)
class RenderOutcome:
    kind: RenderOutcomeKind
    result: RenderResult | None
    violations: tuple[str, ...]
    error: str | None


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")


def application_dir(root: Path, company: str, title: str) -> Path:
    return Path(root) / f"{slugify(company)}-{slugify(title)}"


def render_result_to_dict(result: RenderResult) -> dict[str, object]:
    return {
        "schema_version": result.schema_version,
        "job_id": result.job_id,
        "company": result.company,
        "title": result.title,
        "alignment_fingerprint": result.alignment_fingerprint,
        "s3_bundle_schema_version": result.s3_bundle_schema_version,
        "source_path": result.source_path,
        "pdf_path": result.pdf_path,
        "pdf_sha256": result.pdf_sha256,
        "page_count": result.page_count,
        "size_bytes": result.size_bytes,
        "modified_bullet_ids": list(result.modified_bullet_ids),
        "modified_bullet_line_counts": [[bid, count] for bid, count in result.modified_bullet_line_counts],
        "l7_violations": list(result.l7_violations),
        "render_line_check": result.render_line_check,
    }


class RenderResultError(ValueError):
    """Raised when a persisted render_result.json cannot be parsed."""


_RENDER_RESULT_KEYS = {
    "schema_version", "job_id", "company", "title", "alignment_fingerprint",
    "s3_bundle_schema_version", "source_path", "pdf_path", "pdf_sha256",
    "page_count", "size_bytes", "modified_bullet_ids", "modified_bullet_line_counts",
    "l7_violations", "render_line_check",
}


def parse_render_result(raw: object) -> RenderResult:
    if not isinstance(raw, dict) or set(raw) != _RENDER_RESULT_KEYS:
        raise RenderResultError("$: unexpected field set for a render_result")
    if raw["render_line_check"] not in ("pass", "fail"):
        raise RenderResultError("$.render_line_check: must be 'pass' or 'fail'")
    return RenderResult(
        schema_version=raw["schema_version"], job_id=raw["job_id"], company=raw["company"],
        title=raw["title"], alignment_fingerprint=raw["alignment_fingerprint"],
        s3_bundle_schema_version=raw["s3_bundle_schema_version"], source_path=raw["source_path"],
        pdf_path=raw["pdf_path"], pdf_sha256=raw["pdf_sha256"], page_count=raw["page_count"],
        size_bytes=raw["size_bytes"], modified_bullet_ids=tuple(raw["modified_bullet_ids"]),
        modified_bullet_line_counts=tuple((bid, count) for bid, count in raw["modified_bullet_line_counts"]),
        l7_violations=tuple(raw["l7_violations"]), render_line_check=raw["render_line_check"],
    )


def _write_rejected(reject_dir: Path, tmp_pdf: Path, pdf_name: str, violations: tuple[str, ...]) -> None:
    """Copy a render that failed L7 somewhere a human can look at it. Never
    writes render_result.json; the accepted marker stays absent."""
    reject_dir = Path(reject_dir)
    reject_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(tmp_pdf.with_suffix(".tex"), reject_dir / "resume.tex")
    shutil.copy(tmp_pdf, reject_dir / pdf_name)
    write_json_atomic(reject_dir / "l7_report.json", list(violations))


def render_and_publish(
    profile, draft, *, root: Path, template_path: Path,
    canonical_text_by_id: dict[str, str], s3_bundle_schema_version: str,
    directory: Path | None = None, reject_dir: Path | None = None,
) -> RenderOutcome:
    try:
        doc = render_doc_from_draft(profile, draft)
    except TailoredRenderError as exc:
        message = str(exc)
        kind = RenderOutcomeKind.FINGERPRINT_MISMATCH if "fingerprint" in message else RenderOutcomeKind.MAPPING_FAILURE
        return RenderOutcome(kind, None, (), message)

    directory = Path(directory) if directory is not None else application_dir(root, draft.company, draft.title)
    marker_path = directory / "render_result.json"
    if marker_path.exists():
        existing = parse_render_result(json.loads(marker_path.read_text(encoding="utf-8")))
        if existing.alignment_fingerprint == draft.alignment_fingerprint:
            return RenderOutcome(RenderOutcomeKind.ALREADY_PUBLISHED, existing, (), None)
        return RenderOutcome(
            RenderOutcomeKind.CONFLICT, None, (),
            "an accepted render_result.json already exists for this application "
            "with a different input fingerprint",
        )

    if shutil.which("pdflatex") is None:
        return RenderOutcome(RenderOutcomeKind.RENDERER_UNAVAILABLE, None, (), "pdflatex not found on PATH")

    modified_ids = modified_bullet_ids(draft, canonical_text_by_id)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_pdf = Path(tmp) / "resume.pdf"
        try:
            render_latex(doc, template_path, tmp_pdf)
        except Exception as exc:
            return RenderOutcome(RenderOutcomeKind.RENDERER_FAILURE, None, (), str(exc))

        try:
            parsed = parse_pdf(tmp_pdf)
            pages = parse_rendered_lines(tmp_pdf)
        except Exception as exc:
            return RenderOutcome(RenderOutcomeKind.PARSE_FAILURE, None, (), str(exc))

        violations = tuple(run_l7_tailored(doc, parsed, pages, modified_ids))
        if violations:
            if reject_dir is not None:
                _write_rejected(Path(reject_dir), tmp_pdf, profile.ats["filename_pattern"], violations)
            return RenderOutcome(RenderOutcomeKind.L7_FAILURE, None, violations, None)

        directory.mkdir(parents=True, exist_ok=True)
        tmp_tex = tmp_pdf.with_suffix(".tex")
        pdf_name = profile.ats["filename_pattern"]
        shutil.copy(tmp_tex, directory / "resume.tex")
        shutil.copy(tmp_pdf, directory / pdf_name)
        (directory / "l7_report.json").write_text(json.dumps([]), encoding="utf-8")

        line_counts = tuple(
            (bullet.bullet_id, len(locate_text_lines(pages, bullet.text)))
            for bullet in doc.all_bullets()
            if bullet.bullet_id in modified_ids
        )
        result = RenderResult(
            schema_version=RENDER_RESULT_SCHEMA, job_id=draft.job_id, company=draft.company,
            title=draft.title, alignment_fingerprint=draft.alignment_fingerprint,
            s3_bundle_schema_version=s3_bundle_schema_version,
            source_path=str(directory / "resume.tex"), pdf_path=str(directory / pdf_name),
            pdf_sha256=hashlib.sha256((directory / pdf_name).read_bytes()).hexdigest(),
            page_count=parsed.page_count, size_bytes=(directory / pdf_name).stat().st_size,
            modified_bullet_ids=tuple(sorted(modified_ids)),
            modified_bullet_line_counts=line_counts, l7_violations=(),
            render_line_check="pass",
        )
        write_json_atomic(marker_path, render_result_to_dict(result))
        return RenderOutcome(RenderOutcomeKind.VALID, result, (), None)
