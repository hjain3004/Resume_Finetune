import argparse
import sys
import json
from pathlib import Path
from src.profile import load_profile
from src.llm_tailor.lane import LLMTailorLane, LaneHalted
from src.llm_tailor.validators import validate_audit_integrity
from src.render.model import RenderDoc, RenderEntry, RenderBullet
from src.render.rendercv import render_rendercv
from src.render.latex import render_latex
import subprocess


def build_parser():
    p = argparse.ArgumentParser()
    p.add_argument("--jd", required=True)
    p.add_argument("--db", required=True)
    p.add_argument("--output-dir", required=True)
    return p

def main():
    args = build_parser().parse_args()
    
    jd_path = Path(args.jd)
    jd_text = jd_path.read_text(encoding="utf-8")
    
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    profile = load_profile("config/master_profile.yaml")
    
    lane = LLMTailorLane(profile, trace_dir=out_dir / "traces")
    run_id = "run_tiktok"
    
    try:
        print("\nRunning draft...")
        draft = lane.run_draft(jd_text, run_id)
        
        print("\n\n--- TikTok Selection Manifest ---")
        print("\n\nRequirements to Evidence mapping:")
        for req in draft.requirements:
            print(f"- {req.requirement} (Span: {req.source_span_id}) -> {req.evidence_ids}")
            
        print("\n\nSelected Bullet IDs:")
        selected_ids = {b.id for b in draft.bullets}
        for b in draft.bullets:
            print(f"- {b.id}")
            
        print("\n\nAmdocs Inclusion/Omission Decisions:")
        amdocs_ids = {
            "am_b00_order_management_domain", "am_b01_dlq_consolidation", "am_b02_row_level_entitlement",
            "am_b03_audit_trail", "am_b04_data_retention", "am_b05_test_automation", "am_b06_aws_ci_and_resilience"
        }
        for aid in sorted(amdocs_ids):
            if aid in selected_ids:
                print(f"- {aid}: SELECTED")
            else:
                print(f"- {aid}: OMITTED (Reason: {draft.omitted_evidence_ids.get(aid, 'No rationale provided')})")
                
        print("\n\nMalyTech Inclusion/Omission Decisions:")
        malytech_ids = {b.id for entry in profile.experience if entry.id == "bank_integration_internship" for b in entry.bullets}
        for aid in sorted(malytech_ids):
            if aid in selected_ids:
                print(f"- {aid}: SELECTED")
            else:
                print(f"- {aid}: OMITTED (Reason: {draft.omitted_evidence_ids.get(aid, 'No rationale provided')})")
                
        print("\n\nProposed Bullet Prose:")
        for b in draft.bullets:
            print(f"[{b.id}] {b.text}")
            
        print("\n\nRunning audit...")
        audit = lane.run_audit(jd_text, draft, run_id)
        
        print("\n\nAudit Result:")
        for res in audit.results:
            status = "ACCEPTED" if res.accepted else f"REJECTED: {res.rejection_reason}"
            print(f"[{res.id}] {status}")
            
        out_dir.joinpath("draft.json").write_text(draft.model_dump_json(indent=2))
        out_dir.joinpath("audit.json").write_text(audit.model_dump_json(indent=2))
        

        lane.enforce_deterministic_validators(draft, jd_text)
        
        audit_violations = validate_audit_integrity(audit)
        if audit_violations:
            raise LaneHalted("Audit Integrity validation failed:\n" + "\n".join(audit_violations))

        
        # Render the PDF
        print("\nRendering PDF...")


        def build_doc(bullets_to_keep):
            exp_entries = []
            for entry in profile.experience:
                entry_bullets = [b for b in bullets_to_keep if b.entry_id == entry.id]
                if not entry_bullets: continue
                exp_entries.append(RenderEntry(
                    entry_id=entry.id,
                    heading=entry.employer,
                    subheading=entry.title,
                    date_range=entry.display_date,
                    location="",
                    bullets=tuple([RenderBullet(bullet_id=b.id, text=b.text) for b in entry_bullets])
                ))
                
            proj_entries = []
            for entry in profile.projects:
                entry_bullets = [b for b in bullets_to_keep if b.entry_id == entry.id]
                if not entry_bullets: continue
                proj_entries.append(RenderEntry(
                    entry_id=entry.id,
                    heading=entry.display_title,
                    subheading=entry.tech_line,
                    bullets=tuple([RenderBullet(bullet_id=b.id, text=b.text) for b in entry_bullets])
                ))
                
            edu_entries = []
            for edu in profile.education:
                edu_entries.append(RenderEntry(
                    entry_id=edu.institution,
                    heading=edu.institution,
                    subheading=edu.degree,
                    date_range=edu.display_date,
                    location="",
                    bullets=()
                ))
                
            return RenderDoc(
                identity={
                    "name": profile.contact.name,
                    "email": profile.contact.email,
                    "phone": profile.contact.phone,
                    "linkedin": profile.contact.linkedin,
                    "github": profile.contact.github
                },
                education=tuple(edu_entries),
                experience=tuple(exp_entries),
                projects=tuple(proj_entries),
                skills=profile.skills,
                section_order=("education", "experience", "projects", "skills"),
                ats={"role_id": "123", "company": "TikTok", "role_title": "Backend"}
            )
            
        pdf_path = out_dir / "resume.pdf"
        current_bullets = list(draft.bullets)
        
        while True:
            doc = build_doc(current_bullets)
            try:
                render_latex(doc, Path("config/templates/sb2cv.tex"), pdf_path)
                from src.render.pdf_metrics import measure_pdf
                metrics = measure_pdf(pdf_path)
                
                print(f"\nRender Metrics: {metrics.pages} pages, {metrics.fill_percentage:.2f}% fill")
                
                if metrics.pages > 1:
                    print("Overflow detected. Looking for a bullet to cut...")
                    # Find lowest priority bullet to cut. Prioritize cutting int_b13 first.
                    ids = [b.id for b in current_bullets]
                    if "int_b13" in ids:
                        print("Cutting int_b13 to resolve overflow.")
                        current_bullets = [b for b in current_bullets if b.id != "int_b13"]
                        continue
                    else:
                        print("No safe lower-priority bullets left to cut.")
                        break
                else:
                    break
                    
            except Exception as e:
                print(f"Render failed: {e}")
                break


        
        print("\nHalting for user approval of prose. The lane implementation is ready.")

        
    except LaneHalted as e:
        print(f"Lane halted: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
