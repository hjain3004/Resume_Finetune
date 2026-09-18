import argparse
import sys
import json
from pathlib import Path
from src.profile import load_profile
from src.llm_tailor.lane import LLMTailorLane, LaneHalted
from src.llm_tailor.schemas import DraftResponse, AuditResponse, AuditBulletResult

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
    
    try:
        print("Loading mocked draft...")
        draft_json = Path("mock_draft.json").read_text()
        draft = DraftResponse.model_validate_json(draft_json)
        
        print("\n--- TikTok Selection Manifest ---")
        print("\nRequirements to Evidence mapping:")
        for req in draft.requirements:
            print(f"- {req.requirement} (Span: {req.source_span_id}) -> {req.evidence_ids}")
            
        print("\nSelected Bullet IDs:")
        selected_ids = {b.id for b in draft.bullets}
        for b in draft.bullets:
            print(f"- {b.id}")
            
        print("\nAmdocs Inclusion/Omission Decisions:")
        amdocs_ids = {
            "am_b00_order_management_domain", "am_b01_dlq_consolidation", "am_b02_row_level_entitlement",
            "am_b03_audit_trail", "am_b04_data_retention", "am_b05_test_automation", "am_b06_aws_ci_and_resilience"
        }
        for aid in sorted(amdocs_ids):
            if aid in selected_ids:
                print(f"- {aid}: SELECTED")
            else:
                print(f"- {aid}: OMITTED (Reason: {draft.omitted_evidence_ids.get(aid, 'No rationale provided')})")
                
        print("\nMalyTech Inclusion/Omission Decisions:")
        malytech_ids = {b.id for entry in profile.experience if entry.id == "bank_integration_internship" for b in entry.bullets}
        for aid in sorted(malytech_ids):
            if aid in selected_ids:
                print(f"- {aid}: SELECTED")
            else:
                print(f"- {aid}: OMITTED (Reason: {draft.omitted_evidence_ids.get(aid, 'No rationale provided')})")
                
        print("\nProposed Bullet Prose:")
        for b in draft.bullets:
            print(f"[{b.id}] {b.text}")
            
        print("\nRunning mocked audit...")
        # Mock audit accepting all bullets
        results = []
        for b in draft.bullets:
            results.append(AuditBulletResult(
                id=b.id, evidence_ids=b.evidence_ids, accepted=True, rejection_reason=None,
                fidelity_ok=True, coherence_ok=True, relevance_ok=True, readability_ok=True
            ))
        audit = AuditResponse(results=results)
        
        print("\nAudit Result:")
        for res in audit.results:
            status = "ACCEPTED" if res.accepted else f"REJECTED: {res.rejection_reason}"
            print(f"[{res.id}] {status}")
            
        out_dir.joinpath("draft.json").write_text(draft.model_dump_json(indent=2))
        out_dir.joinpath("audit.json").write_text(audit.model_dump_json(indent=2))
        
        lane.enforce_deterministic_validators(draft, jd_text)
        
        print("\nHalting for user approval of prose. The lane implementation is ready.")
        
    except LaneHalted as e:
        print(f"Lane halted: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
