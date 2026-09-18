"""Tailor2 end-to-end pipeline orchestrator and artifact publisher.

Policy (see docs/tailor2_quality_core.md for the full design rationale):
fail-closed for factual integrity, repair-first for writing quality,
warning-oriented for evidence gaps, artifact-preserving at every stage.
A quality defect is not a fatal rejection; the only things that ever
produce REJECTED_FATAL are the FATAL_INTEGRITY cases enumerated in
severity.py (fabricated/unresolved evidence, invented numbers, prohibited
claims, an irrecoverably invalid structured response, or a document that
cannot be rendered at all).
"""

from __future__ import annotations

import dataclasses
import datetime
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.profile import MasterProfile, load_profile
from src.render.lines import parse_rendered_lines
from src.tailor.artifacts import write_json_atomic
from src.tailor2.audit_projection import ResumeProjection, build_resume_projection
from src.tailor2.invoker import Tailor2Invoker
from src.tailor2.models import (
    AuditResponse,
    DraftResponse,
    Tailor2Manifest,
    audit_response_to_dict,
    draft_response_to_dict,
    manifest_to_dict,
    parse_audit_response,
    parse_draft_response,
    parse_repair_response,
    repair_response_to_dict,
)
from src.tailor2.prompts import build_audit_prompt, build_draft_prompt, build_re_audit_prompt, build_repair_prompt
from src.tailor2.render import compile_draft_to_pdf
from src.tailor2.severity import RunStatus, Severity
from src.tailor2.validators import (
    apply_deterministic_auto_corrections,
    check_skills_advisories,
    classify_evaluation_severity,
    classify_whole_resume_severity,
    validate_audit_response,
    validate_draft_response,
    validate_repair_response,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Tailor2RunResult:
    success: bool
    call_count: int
    repair_performed: bool
    manifest_path: Path
    out_pdf: Path | None = None
    rejection_reasons: list[str] = field(default_factory=list)
    # New: the RunStatus value (see severity.py). Kept alongside `success`
    # (bool) for backward compatibility -- success is True for every status
    # except REJECTED_FATAL, since every other status still produces a
    # usable rendered artifact.
    status: str = ""
    warnings: list[str] = field(default_factory=list)


def _invoker_identity(invoker: Tailor2Invoker) -> tuple[str, str]:
    provider = invoker.provider.value if hasattr(invoker.provider, "value") else str(invoker.provider)
    return provider, invoker.model


@dataclass
class _Stage:
    """Mutable bookkeeping threaded through the run; avoids re-passing a
    dozen loose variables between the helper functions below."""

    run_id: str
    created_at: str
    company: str
    title: str
    variant: str
    call_count: int = 0
    repair_performed: bool = False
    warnings: list[str] = field(default_factory=list)
    auto_corrections: list[str] = field(default_factory=list)
    advisory_gaps: list[str] = field(default_factory=list)
    dimension_scores: dict[str, dict] = field(default_factory=dict)
    drafter_id: tuple[str, str] = ("", "")
    auditor_id: tuple[str, str] = ("", "")
    repair_id: tuple[str, str] = ("", "")
    re_audit_id: tuple[str, str] = ("", "")
    same_model_draft_and_audit: bool = False
    title_resolutions: list[dict[str, Any]] = field(default_factory=list)
    # Set by _audit_repair_cycle once it settles on a final draft; the
    # caller reads these back to proceed to rendering. `needs_human_review`
    # distinguishes "clean pass" from "gave up after the repair budget /
    # no single-bullet repair target existed" -- both leave a usable draft,
    # but only the latter should downgrade the final RunStatus.
    final_draft: DraftResponse | None = None
    final_projection: ResumeProjection | None = None
    needs_human_review: bool = False


def _record_dimension_scores(stage: _Stage, audit: AuditResponse) -> None:
    for ev in audit.evaluations:
        for dim_name, dim in ev.dimensions.items():
            stage.dimension_scores[f"bullet:{ev.bullet_id}:{dim_name}"] = {
                "score": dim.score,
                "findings": dim.findings,
            }
    if audit.whole_resume is not None:
        for dim_name, dim in audit.whole_resume.dimensions.items():
            stage.dimension_scores[f"whole_resume:{dim_name}"] = {
                "score": dim.score,
                "findings": dim.findings,
            }


def _build_manifest(stage: _Stage, run_status: RunStatus, rejection_details: list[str]) -> Tailor2Manifest:
    return Tailor2Manifest(
        run_id=stage.run_id,
        created_at=stage.created_at,
        provider=stage.drafter_id[0],
        model=stage.drafter_id[1],
        company=stage.company,
        title=stage.title,
        variant=stage.variant,
        call_count=stage.call_count,
        repair_performed=stage.repair_performed,
        status=run_status.value,
        rejection_details=rejection_details,
        drafter_provider=stage.drafter_id[0],
        drafter_model=stage.drafter_id[1],
        auditor_provider=stage.auditor_id[0],
        auditor_model=stage.auditor_id[1],
        repair_provider=stage.repair_id[0],
        repair_model=stage.repair_id[1],
        re_audit_provider=stage.re_audit_id[0],
        re_audit_model=stage.re_audit_id[1],
        same_model_draft_and_audit=stage.same_model_draft_and_audit,
        run_status=run_status.value,
        warnings=list(stage.warnings),
        auto_corrections=list(stage.auto_corrections),
        advisory_gaps=list(stage.advisory_gaps),
        dimension_scores=dict(stage.dimension_scores),
        title_resolutions=list(stage.title_resolutions),
    )



def _write_fatal(out_dir: Path, stage: _Stage, reasons: list[str]) -> Tailor2RunResult:
    reject_dir = out_dir / "rejected"
    reject_dir.mkdir(parents=True, exist_ok=True)
    manifest = _build_manifest(stage, RunStatus.REJECTED_FATAL, reasons)
    manifest_path = reject_dir / "run_manifest.json"
    write_json_atomic(manifest_path, manifest_to_dict(manifest))
    return Tailor2RunResult(
        success=False,
        call_count=stage.call_count,
        repair_performed=stage.repair_performed,
        manifest_path=manifest_path,
        rejection_reasons=reasons,
        status=RunStatus.REJECTED_FATAL.value,
        warnings=list(stage.warnings),
    )


def run_tailor2_lane(
    jd_path: Path,
    company: str,
    title: str,
    variant: str,
    invoker: Tailor2Invoker,
    out_dir: Path,
    profile_path: Path = Path("config/master_profile.yaml"),
    template_path: Path = Path("profile/template.tex"),
    auditor_invoker: Tailor2Invoker | None = None,
    repair_invoker: Tailor2Invoker | None = None,
    re_audit_invoker: Tailor2Invoker | None = None,
    acknowledge_same_model: bool = False,
    repair_budget: int = 1,
) -> Tailor2RunResult:
    """Run the LLM-first tailoring pipeline.

    `invoker` is the DRAFTER's model identity -- unchanged in meaning and
    position from before this task, so every existing call site keeps
    working exactly as it did. `auditor_invoker` is a separately
    configured identity for the audit/re-audit stage; when omitted, the
    drafter invoker is reused for audit (the historical single-invoker
    behavior), and a same-model disclosure is recorded in the manifest and
    logged (pass `acknowledge_same_model=True` to suppress the log message
    -- the manifest still records `same_model_draft_and_audit=True` either
    way, so no downstream reader can mistake this for an independent
    review). This disclosure never by itself changes the run's final
    status -- see the "same-model disclosure is informational" note in
    docs/tailor2_quality_core.md. `repair_invoker`/`re_audit_invoker`
    default to `auditor_invoker` (i.e. the audit-side identity performs
    repair and re-audit unless told otherwise).
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    jd_path = Path(jd_path)
    jd_text = jd_path.read_text(encoding="utf-8")

    profile = load_profile(profile_path)

    auditor_invoker = auditor_invoker or invoker
    repair_invoker = repair_invoker or auditor_invoker
    re_audit_invoker = re_audit_invoker or auditor_invoker

    stage = _Stage(
        run_id=datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        created_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        company=company,
        title=title,
        variant=variant,
        drafter_id=_invoker_identity(invoker),
        auditor_id=_invoker_identity(auditor_invoker),
        repair_id=_invoker_identity(repair_invoker),
        re_audit_id=_invoker_identity(re_audit_invoker),
    )
    stage.same_model_draft_and_audit = stage.drafter_id == stage.auditor_id
    if stage.same_model_draft_and_audit:
        msg = (
            f"Drafter and auditor share the same provider/model ({stage.drafter_id[0]}:{stage.drafter_id[1]}); "
            "this audit is NOT an independent cross-model review. Pass a distinct auditor_invoker for genuine "
            "independence."
        )
        if not acknowledge_same_model:
            logger.warning(msg)
        stage.warnings.append(msg)

    # Save copy of job description
    (out_dir / "job_description.txt").write_text(jd_text, encoding="utf-8")

    # ---------------------------------------------------------
    # STAGE 1: DRAFT
    # ---------------------------------------------------------
    draft_prompt = build_draft_prompt(jd_text, profile, variant, company, title)
    try:
        raw_draft = invoker.invoke(draft_prompt, invocation_type="draft", input_paths=[jd_path])
        stage.call_count += 1
        draft = parse_draft_response(raw_draft)
        validate_draft_response(draft, jd_text, profile, variant)
    except Exception as exc:
        # Malformed/invalid structured response or a deterministic evidence/
        # do_not_claim/numeric-token violation: both are FATAL_INTEGRITY --
        # neither can be repaired without inventing evidence.
        return _write_fatal(out_dir, stage, [str(exc)])

    write_json_atomic(out_dir / "draft.json", draft_response_to_dict(draft))

    fatal_result = _audit_repair_cycle(
        jd_path=jd_path,
        jd_text=jd_text,
        profile=profile,
        company=company,
        title=title,
        variant=variant,
        draft=draft,
        out_dir=out_dir,
        stage=stage,
        auditor_invoker=auditor_invoker,
        repair_invoker=repair_invoker,
        re_audit_invoker=re_audit_invoker,
        repair_budget=repair_budget,
    )
    if fatal_result is not None:
        return fatal_result

    final_draft = stage.final_draft
    final_projection = stage.final_projection
    assert final_draft is not None and final_projection is not None  # guaranteed by _audit_repair_cycle contract

    # ADVISORY_GAP: a must_have atomic requirement with no supporting
    # bullet is a real capability the profile has no evidence for (e.g. a
    # JD asking for React when nothing in master_profile.yaml demonstrates
    # it). Disclosed, never invented, never blocks completion.
    for req in final_projection.requirement_coverage:
        if req.importance == "must_have" and not req.covered:
            stage.advisory_gaps.append(
                f"Requirement {req.id!r} ({req.term!r}) has no supporting evidence in the selected profile bullets."
            )

    # ---------------------------------------------------------
    # RENDER & L7 GATE
    # ---------------------------------------------------------
    resolved_titles = {
        e.entry_id: e.displayed_title_or_tech for e in final_projection.entries if e.kind == "Experience"
    }
    filtered_skills = {cat: tuple(s.term for s in terms) for cat, terms in final_projection.skills.items()}
    try:
        tex_path, pdf_path, render_doc = compile_draft_to_pdf(
            final_draft, profile, out_dir, template_path, resolved_titles, filtered_skills
        )
    except Exception as exc:
        # Compilation itself failed -- a corrupted/unrenderable document is
        # explicitly FATAL_INTEGRITY (cannot be repaired without inventing
        # a working document).
        return _write_fatal(out_dir, stage, [f"Render failed: {exc}"])

    try:
        pages = parse_rendered_lines(pdf_path)
    except Exception as exc:
        return _write_fatal(out_dir, stage, [f"Could not parse rendered PDF: {exc}"])

    page_overflow = len(pages) != 1
    if page_overflow:
        # Page-fill variance is NOT a fatal defect (explicit override in
        # this task): the résumé compiled successfully, it is just not
        # exactly one page. Preserve the artifact and mark for human
        # review rather than discarding it.
        stage.warnings.append(f"Compiled PDF has {len(pages)} page(s) (expected 1); preserved for human review.")

    # ---------------------------------------------------------
    # FINAL STATUS RESOLUTION
    # ---------------------------------------------------------
    if page_overflow or stage.needs_human_review:
        run_status = RunStatus.NEEDS_HUMAN_REVIEW
    elif stage.auto_corrections or stage.advisory_gaps or any("Skills advisory" in w for w in stage.warnings):
        run_status = RunStatus.ACCEPTED_WITH_WARNINGS
    else:
        run_status = RunStatus.ACCEPTED

    manifest = _build_manifest(stage, run_status, [])
    manifest_path = out_dir / "run_manifest.json"
    write_json_atomic(manifest_path, manifest_to_dict(manifest))

    return Tailor2RunResult(
        success=True,
        call_count=stage.call_count,
        repair_performed=stage.repair_performed,
        manifest_path=manifest_path,
        out_pdf=pdf_path,
        status=run_status.value,
        warnings=list(stage.warnings),
    )


def _audit_repair_cycle(
    *,
    jd_path: Path,
    jd_text: str,
    profile: MasterProfile,
    company: str,
    title: str,
    variant: str,
    draft: DraftResponse,
    out_dir: Path,
    stage: _Stage,
    auditor_invoker: Tailor2Invoker,
    repair_invoker: Tailor2Invoker,
    re_audit_invoker: Tailor2Invoker,
    repair_budget: int,
) -> Tailor2RunResult | None:
    """Runs audit, then bounded repair+re-audit cycles.

    On a FATAL_INTEGRITY outcome, returns a completed (failed)
    Tailor2RunResult directly. On any non-fatal outcome (clean pass, or
    quality issues that were repaired or that exhausted the repair budget
    / had no single-bullet target), returns None and leaves the final
    state on `stage.final_draft` / `stage.final_projection` /
    `stage.needs_human_review` for the caller to read.
    """
    model_identities = {
        "drafter": {"provider": stage.drafter_id[0], "model": stage.drafter_id[1]},
        "auditor": {"provider": stage.auditor_id[0], "model": stage.auditor_id[1]},
        "repair": {"provider": stage.repair_id[0], "model": stage.repair_id[1]},
        "re_audit": {"provider": stage.re_audit_id[0], "model": stage.re_audit_id[1]},
    }

    evidence_by_id: dict[str, Any] = {}
    for exp in profile.experience:
        for b in exp.bullets:
            evidence_by_id[b.id] = b
    for proj in profile.projects:
        for b in proj.bullets:
            evidence_by_id[b.id] = b

    current_draft = draft
    attempts = 0
    # Bullet ids the *next* audit/re-audit response's `evaluations` array is
    # expected to cover. The first audit evaluates every drafted bullet;
    # each re-audit evaluates only the bullets that were just sent to
    # repair (matching pre-existing fixture/test behavior) -- the
    # WHOLE-RESUME dimensions, scored against the full `corrected_projection`
    # context, are what give the re-audit visibility into the complete
    # repaired résumé; re-scoring every untouched bullet again would be
    # redundant with the scores already recorded from the original audit.
    expected_eval_ids = [b.bullet_id for b in draft.bullets]

    while True:
        projection = build_resume_projection(current_draft, profile, company, title, variant, model_identities)
        corrected_projection, auto_corrections = apply_deterministic_auto_corrections(projection)
        if auto_corrections:
            stage.auto_corrections.extend(auto_corrections)

        # Record title resolutions and route to human review if any unresolved conflict
        if projection.title_resolutions:
            stage.title_resolutions = [dataclasses.asdict(tr) for tr in projection.title_resolutions]
            for tr in projection.title_resolutions:
                if tr.requires_human_review:
                    stage.needs_human_review = True
                    if tr.authority_note not in stage.warnings:
                        stage.warnings.append(tr.authority_note)

        # Record skills advisories for weakly demonstrated skills
        for adv in check_skills_advisories(corrected_projection):
            if adv not in stage.warnings:
                stage.warnings.append(adv)


        if attempts == 0:
            active_invoker = auditor_invoker
            invocation_type = "audit"
            prompt = build_audit_prompt(jd_text, current_draft.bullets, evidence_by_id, corrected_projection)
        else:
            active_invoker = re_audit_invoker
            invocation_type = "re_audit"
            # The complete repaired résumé is embedded in `corrected_projection`
            # (every bullet in final order, not just the repaired fragments),
            # so the fragment-level positional args are intentionally empty --
            # requirement: "re-audit must evaluate the complete repaired
            # résumé, not only repaired bullet fragments."
            prompt = build_re_audit_prompt(jd_text, [], {}, {}, corrected_projection)

        try:
            raw = active_invoker.invoke(prompt, invocation_type=invocation_type, input_paths=[jd_path])
            stage.call_count += 1
            audit = parse_audit_response(raw)
            validate_audit_response(audit, expected_eval_ids)
        except Exception as exc:
            return _write_fatal(out_dir, stage, [str(exc)])

        out_name = "audit.json" if attempts == 0 else "re_audit.json"
        write_json_atomic(out_dir / out_name, audit_response_to_dict(audit))
        _record_dimension_scores(stage, audit)

        if audit.whole_resume is None:
            stage.warnings.append(
                f"{invocation_type}: whole-résumé auditing was not evaluated for this response "
                "(legacy fixture without a 'whole_resume' block); only per-bullet dimensions were checked."
            )

        # Classify every rejection by severity.
        fatal_reasons: list[str] = []
        repairable_bullet_ids: list[str] = []
        for ev in audit.evaluations:
            sev = classify_evaluation_severity(ev)
            if sev == Severity.FATAL_INTEGRITY:
                fatal_reasons.extend(ev.rejection_reasons or [f"bullet {ev.bullet_id}: fatal-tier defect"])
            elif sev == Severity.REPAIRABLE_QUALITY:
                repairable_bullet_ids.append(ev.bullet_id)

        whole_sev = classify_whole_resume_severity(audit.whole_resume)
        if whole_sev == Severity.FATAL_INTEGRITY:
            fatal_reasons.extend(
                audit.whole_resume.rejection_reasons if audit.whole_resume else ["whole-résumé fatal defect"]
            )
        whole_resume_repairable = whole_sev == Severity.REPAIRABLE_QUALITY

        if fatal_reasons:
            return _write_fatal(out_dir, stage, fatal_reasons)

        if not repairable_bullet_ids and not whole_resume_repairable:
            # Clean pass (or nothing beyond AUTO_CORRECTABLE, already applied).
            stage.final_draft = current_draft
            stage.final_projection = corrected_projection
            return None

        if whole_resume_repairable and not repairable_bullet_ids:
            # A cross-cutting, whole-résumé-only quality finding (e.g.
            # repetition spanning bullets no single bullet was individually
            # rejected for) has no unambiguous single-bullet repair target.
            # Deliberately deferred (see docs/tailor2_quality_core.md,
            # "Known limitations"): rather than guess which bullets to
            # rewrite, surface it for human review with the best available
            # artifact instead of looping or rejecting.
            reasons = (
                audit.whole_resume.rejection_reasons
                if audit.whole_resume and audit.whole_resume.rejection_reasons
                else ["whole-résumé quality finding with no single-bullet repair target"]
            )
            stage.warnings.extend(f"whole_resume (needs human review): {r}" for r in reasons)
            stage.needs_human_review = True
            stage.final_draft = current_draft
            stage.final_projection = corrected_projection
            return None

        attempts += 1
        if attempts > repair_budget:
            # Repair budget exhausted with a REPAIRABLE_QUALITY issue still
            # outstanding: NEEDS_HUMAN_REVIEW, not a rejection. The current
            # draft (this run's best safe candidate -- every prior repair
            # round passed deterministic validation) is still delivered.
            for ev in audit.evaluations:
                if ev.bullet_id in repairable_bullet_ids:
                    stage.warnings.append(
                        f"bullet {ev.bullet_id} (unresolved after repair budget): "
                        f"{'; '.join(ev.rejection_reasons) or 'quality finding'}"
                    )
            stage.needs_human_review = True
            stage.final_draft = current_draft
            stage.final_projection = corrected_projection
            return None

        stage.repair_performed = True
        rejected_evals = {ev.bullet_id: ev for ev in audit.evaluations if ev.bullet_id in repairable_bullet_ids}
        rejected_bullets = [b for b in current_draft.bullets if b.bullet_id in rejected_evals]

        findings_by_bullet = {}
        for bid, ev in rejected_evals.items():
            findings_by_bullet[bid] = [
                {"dimension": d_name, "score": d_val.score, "findings": d_val.findings}
                for d_name, d_val in ev.dimensions.items()
                if d_val.score == 1
            ]
            if not findings_by_bullet[bid] and ev.rejection_reasons:
                findings_by_bullet[bid] = [
                    {"dimension": "rejection_reasons", "score": 1, "findings": "; ".join(ev.rejection_reasons)}
                ]

        # Protected facts: every OTHER bullet's evidence/numeric contract,
        # so the repair model has context that it must not alter anything
        # outside its editable targets. Bounded to keep the prompt sane on
        # large résumés.
        protected_facts = [
            f"bullet {b.bullet_id} cites evidence {b.evidence_ids}; its text and every numeric token in it are "
            "OUT OF SCOPE for this repair call and must not change"
            for b in current_draft.bullets
            if b.bullet_id not in rejected_evals
        ][:20]

        repair_prompt = build_repair_prompt(
            rejected_bullets, evidence_by_id, findings_by_bullet, corrected_projection, protected_facts
        )
        try:
            raw_repair = repair_invoker.invoke(repair_prompt, invocation_type="repair")
            stage.call_count += 1
            repair = parse_repair_response(raw_repair)
            validate_repair_response(
                repair,
                [b.bullet_id for b in rejected_bullets],
                {b.bullet_id: b.evidence_ids for b in rejected_bullets},
                evidence_by_id,
                profile,
            )
        except Exception as exc:
            return _write_fatal(out_dir, stage, [str(exc)])

        write_json_atomic(out_dir / "repair.json", repair_response_to_dict(repair))

        repaired_text_by_id = {rb.bullet_id: rb.text for rb in repair.repaired_bullets}
        new_bullets = [
            dataclasses.replace(b, text=repaired_text_by_id[b.bullet_id]) if b.bullet_id in repaired_text_by_id else b
            for b in current_draft.bullets
        ]
        candidate_draft = dataclasses.replace(current_draft, bullets=new_bullets)

        try:
            validate_draft_response(candidate_draft, jd_text, profile, variant)
        except Exception as exc:
            # The repair passed its own fabrication checks
            # (validate_repair_response, above) but broke a structural
            # layout invariant (e.g. a blueprint bullet-count bound) --
            # this is a repair making the résumé WORSE, not evidence
            # fabrication. Per "preserve the best pre-repair candidate as
            # a fallback," serve the last known-good draft (which already
            # passed this exact check) instead of rejecting the whole run.
            stage.warnings.append(
                f"repair attempt {attempts} produced a structurally invalid draft ({exc}); "
                "falling back to the pre-repair candidate for this bullet."
            )
            stage.needs_human_review = True
            stage.final_draft = current_draft
            stage.final_projection = corrected_projection
            return None

        write_json_atomic(out_dir / "draft_repaired.json", draft_response_to_dict(candidate_draft))
        current_draft = candidate_draft
        expected_eval_ids = list(rejected_evals.keys())
        # Loop: re-audit the complete repaired résumé (full projection
        # context) but validate the evaluations array against just the
        # bullets sent to repair, on the next iteration.
