"""Tailor2 end-to-end pipeline orchestrator and artifact publisher."""

from __future__ import annotations

import dataclasses
import datetime
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.profile import MasterProfile, load_profile
from src.render.lines import parse_rendered_lines
from src.render.parse import parse_pdf
from src.tailor.artifacts import write_json_atomic
from src.tailor2.invoker import Tailor2Invoker
from src.tailor2.models import (
    AuditResponse,
    DraftResponse,
    RepairResponse,
    Tailor2Manifest,
    audit_response_to_dict,
    draft_response_to_dict,
    manifest_to_dict,
    parse_audit_response,
    parse_draft_response,
    parse_repair_response,
    repair_response_to_dict,
)
from src.tailor2.prompts import (
    build_audit_prompt,
    build_draft_prompt,
    build_re_audit_prompt,
    build_repair_prompt,
)
from src.tailor2.render import compile_draft_to_pdf
from src.tailor2.validators import (
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


def run_tailor2_lane(
    jd_path: Path,
    company: str,
    title: str,
    variant: str,
    invoker: Tailor2Invoker,
    out_dir: Path,
    profile_path: Path = Path("config/master_profile.yaml"),
    template_path: Path = Path("profile/template.tex"),
) -> Tailor2RunResult:
    """Run the 4-stage LLM-first tailoring pipeline."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    jd_path = Path(jd_path)
    jd_text = jd_path.read_text(encoding="utf-8")

    profile = load_profile(profile_path)
    evidence_by_id = {}
    for exp in profile.experience:
        for b in exp.bullets:
            evidence_by_id[b.id] = b
    for proj in profile.projects:
        for b in proj.bullets:
            evidence_by_id[b.id] = b

    run_id = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    call_count = 0
    repair_performed = False

    # Save copy of job description
    (out_dir / "job_description.txt").write_text(jd_text, encoding="utf-8")

    # ---------------------------------------------------------
    # STAGE 1: DRAFT
    # ---------------------------------------------------------
    draft_prompt = build_draft_prompt(jd_text, profile, variant, company, title)
    try:
        raw_draft = invoker.invoke(draft_prompt, invocation_type="draft", input_paths=[jd_path])
        call_count += 1
        draft = parse_draft_response(raw_draft)
        validate_draft_response(draft, jd_text, profile, variant)
    except Exception as exc:
        reject_dir = out_dir / "rejected"
        reject_dir.mkdir(parents=True, exist_ok=True)
        manifest = Tailor2Manifest(
            run_id=run_id,
            created_at=created_at,
            provider=invoker.provider.value if hasattr(invoker.provider, "value") else str(invoker.provider),
            model=invoker.model,
            company=company,
            title=title,
            variant=variant,
            call_count=call_count,
            repair_performed=repair_performed,
            status="FAILED_DRAFT",
            rejection_details=[str(exc)],
        )
        manifest_path = reject_dir / "run_manifest.json"
        write_json_atomic(manifest_path, manifest_to_dict(manifest))
        return Tailor2RunResult(
            success=False,
            call_count=call_count,
            repair_performed=repair_performed,
            manifest_path=manifest_path,
            rejection_reasons=[str(exc)],
        )

    write_json_atomic(out_dir / "draft.json", draft_response_to_dict(draft))

    # ---------------------------------------------------------
    # STAGE 2: INDEPENDENT AUDIT
    # ---------------------------------------------------------
    audit_prompt = build_audit_prompt(jd_text, draft.bullets, evidence_by_id)
    try:
        raw_audit = invoker.invoke(audit_prompt, invocation_type="audit", input_paths=[jd_path])
        call_count += 1
        audit = parse_audit_response(raw_audit)
        validate_audit_response(audit, [b.bullet_id for b in draft.bullets])
    except Exception as exc:
        reject_dir = out_dir / "rejected"
        reject_dir.mkdir(parents=True, exist_ok=True)
        manifest = Tailor2Manifest(
            run_id=run_id,
            created_at=created_at,
            provider=invoker.provider.value if hasattr(invoker.provider, "value") else str(invoker.provider),
            model=invoker.model,
            company=company,
            title=title,
            variant=variant,
            call_count=call_count,
            repair_performed=repair_performed,
            status="FAILED_AUDIT",
            rejection_details=[str(exc)],
        )
        manifest_path = reject_dir / "run_manifest.json"
        write_json_atomic(manifest_path, manifest_to_dict(manifest))
        return Tailor2RunResult(
            success=False,
            call_count=call_count,
            repair_performed=repair_performed,
            manifest_path=manifest_path,
            rejection_reasons=[str(exc)],
        )

    write_json_atomic(out_dir / "audit.json", audit_response_to_dict(audit))

    # ---------------------------------------------------------
    # STAGES 3 & 4: CONDITIONAL REPAIR & RE-AUDIT
    # ---------------------------------------------------------
    if audit.overall_verdict == "REPAIR_REQUIRED":
        repair_performed = True
        rejected_evals = {ev.bullet_id: ev for ev in audit.evaluations if ev.verdict == "REJECT"}
        rejected_bullets = [b for b in draft.bullets if b.bullet_id in rejected_evals]

        findings_by_bullet = {}
        for bid, ev in rejected_evals.items():
            findings_by_bullet[bid] = [
                {"dimension": d_name, "score": d_val.score, "findings": d_val.findings}
                for d_name, d_val in ev.dimensions.items()
                if d_val.score == 1
            ]
            if not findings_by_bullet[bid] and ev.rejection_reasons:
                findings_by_bullet[bid] = [{"dimension": "rejection_reasons", "score": 1, "findings": "; ".join(ev.rejection_reasons)}]

        # Stage 3: Repair
        repair_prompt = build_repair_prompt(rejected_bullets, evidence_by_id, findings_by_bullet)
        try:
            raw_repair = invoker.invoke(repair_prompt, invocation_type="repair")
            call_count += 1
            repair = parse_repair_response(raw_repair)
            validate_repair_response(
                repair,
                [b.bullet_id for b in rejected_bullets],
                {b.bullet_id: b.evidence_ids for b in rejected_bullets},
                evidence_by_id,
                profile,
            )
        except Exception as exc:
            reject_dir = out_dir / "rejected"
            reject_dir.mkdir(parents=True, exist_ok=True)
            manifest = Tailor2Manifest(
                run_id=run_id,
                created_at=created_at,
                provider=invoker.provider.value if hasattr(invoker.provider, "value") else str(invoker.provider),
                model=invoker.model,
                company=company,
                title=title,
                variant=variant,
                call_count=call_count,
                repair_performed=repair_performed,
                status="FAILED_REPAIR",
                rejection_details=[str(exc)],
            )
            manifest_path = reject_dir / "run_manifest.json"
            write_json_atomic(manifest_path, manifest_to_dict(manifest))
            return Tailor2RunResult(
                success=False,
                call_count=call_count,
                repair_performed=repair_performed,
                manifest_path=manifest_path,
                rejection_reasons=[str(exc)],
            )

        write_json_atomic(out_dir / "repair.json", repair_response_to_dict(repair))

        # Stage 4: Re-Audit
        bullet_entries = {b.bullet_id: (b.section, b.entry_id, b.evidence_ids) for b in rejected_bullets}
        re_audit_prompt = build_re_audit_prompt(jd_text, repair.repaired_bullets, evidence_by_id, bullet_entries)
        try:
            raw_re_audit = invoker.invoke(re_audit_prompt, invocation_type="re_audit", input_paths=[jd_path])
            call_count += 1
            re_audit = parse_audit_response(raw_re_audit)
            validate_audit_response(re_audit, [b.bullet_id for b in repair.repaired_bullets])
        except Exception as exc:
            reject_dir = out_dir / "rejected"
            reject_dir.mkdir(parents=True, exist_ok=True)
            manifest = Tailor2Manifest(
                run_id=run_id,
                created_at=created_at,
                provider=invoker.provider.value if hasattr(invoker.provider, "value") else str(invoker.provider),
                model=invoker.model,
                company=company,
                title=title,
                variant=variant,
                call_count=call_count,
                repair_performed=repair_performed,
                status="FAILED_RE_AUDIT",
                rejection_details=[str(exc)],
            )
            manifest_path = reject_dir / "run_manifest.json"
            write_json_atomic(manifest_path, manifest_to_dict(manifest))
            return Tailor2RunResult(
                success=False,
                call_count=call_count,
                repair_performed=repair_performed,
                manifest_path=manifest_path,
                rejection_reasons=[str(exc)],
            )

        write_json_atomic(out_dir / "re_audit.json", audit_response_to_dict(re_audit))

        if re_audit.overall_verdict != "PASS":
            reject_dir = out_dir / "rejected"
            reject_dir.mkdir(parents=True, exist_ok=True)
            rejection_reasons = []
            for ev in re_audit.evaluations:
                if ev.verdict == "REJECT":
                    rejection_reasons.extend(ev.rejection_reasons or ["Unresolved defect on re-audit"])

            manifest = Tailor2Manifest(
                run_id=run_id,
                created_at=created_at,
                provider=invoker.provider.value if hasattr(invoker.provider, "value") else str(invoker.provider),
                model=invoker.model,
                company=company,
                title=title,
                variant=variant,
                call_count=call_count,
                repair_performed=repair_performed,
                status="FAILED_RE_AUDIT_VERDICT",
                rejection_details=rejection_reasons,
            )
            manifest_path = reject_dir / "run_manifest.json"
            write_json_atomic(manifest_path, manifest_to_dict(manifest))
            return Tailor2RunResult(
                success=False,
                call_count=call_count,
                repair_performed=repair_performed,
                manifest_path=manifest_path,
                rejection_reasons=rejection_reasons,
            )

        # Splice repaired bullets into draft
        repaired_text_by_id = {rb.bullet_id: rb.text for rb in repair.repaired_bullets}
        new_bullets = []
        for b in draft.bullets:
            if b.bullet_id in repaired_text_by_id:
                new_bullets.append(dataclasses.replace(b, text=repaired_text_by_id[b.bullet_id]))
            else:
                new_bullets.append(b)
        draft = dataclasses.replace(draft, bullets=new_bullets)

        # Re-validate the complete spliced draft deterministically
        try:
            validate_draft_response(draft, jd_text, profile, variant)
        except Exception as exc:
            reject_dir = out_dir / "rejected"
            reject_dir.mkdir(parents=True, exist_ok=True)
            manifest = Tailor2Manifest(
                run_id=run_id,
                created_at=created_at,
                provider=invoker.provider.value if hasattr(invoker.provider, "value") else str(invoker.provider),
                model=invoker.model,
                company=company,
                title=title,
                variant=variant,
                call_count=call_count,
                repair_performed=repair_performed,
                status="FAILED_REPAIRED_DRAFT_VALIDATION",
                rejection_details=[str(exc)],
            )
            manifest_path = reject_dir / "run_manifest.json"
            write_json_atomic(manifest_path, manifest_to_dict(manifest))
            return Tailor2RunResult(
                success=False,
                call_count=call_count,
                repair_performed=repair_performed,
                manifest_path=manifest_path,
                rejection_reasons=[str(exc)],
            )

        write_json_atomic(out_dir / "draft_repaired.json", draft_response_to_dict(draft))

    # ---------------------------------------------------------
    # STAGE 5: RENDER & L7 GATE
    # ---------------------------------------------------------
    try:
        tex_path, pdf_path, render_doc = compile_draft_to_pdf(draft, profile, out_dir, template_path)
        pages = parse_rendered_lines(pdf_path)
        if len(pages) != 1:
            raise ValueError(f"Compiled PDF has {len(pages)} pages; exactly 1 page required")
    except Exception as exc:
        reject_dir = out_dir / "rejected"
        reject_dir.mkdir(parents=True, exist_ok=True)
        manifest = Tailor2Manifest(
            run_id=run_id,
            created_at=created_at,
            provider=invoker.provider.value if hasattr(invoker.provider, "value") else str(invoker.provider),
            model=invoker.model,
            company=company,
            title=title,
            variant=variant,
            call_count=call_count,
            repair_performed=repair_performed,
            status="FAILED_RENDER_L7",
            rejection_details=[str(exc)],
        )
        manifest_path = reject_dir / "run_manifest.json"
        write_json_atomic(manifest_path, manifest_to_dict(manifest))
        return Tailor2RunResult(
            success=False,
            call_count=call_count,
            repair_performed=repair_performed,
            manifest_path=manifest_path,
            rejection_reasons=[str(exc)],
        )

    # ---------------------------------------------------------
    # STAGE 6: ATOMIC SUCCESS PUBLICATION
    # ---------------------------------------------------------
    manifest = Tailor2Manifest(
        run_id=run_id,
        created_at=created_at,
        provider=invoker.provider.value if hasattr(invoker.provider, "value") else str(invoker.provider),
        model=invoker.model,
        company=company,
        title=title,
        variant=variant,
        call_count=call_count,
        repair_performed=repair_performed,
        status="ACCEPTED",
        rejection_details=[],
    )
    manifest_path = out_dir / "run_manifest.json"
    write_json_atomic(manifest_path, manifest_to_dict(manifest))

    return Tailor2RunResult(
        success=True,
        call_count=call_count,
        repair_performed=repair_performed,
        manifest_path=manifest_path,
        out_pdf=pdf_path,
    )
