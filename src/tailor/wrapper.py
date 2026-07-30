def hydrate_tailor_draft(tailor_json: dict, master_profile: dict) -> str:
    """Hydrate the structural tailor output into a plain text resume."""
    parts = []
    
    parts.append("SKILLS")
    for category, items in tailor_json.get("skills", {}).items():
        parts.append(f"{category}: {', '.join(items)}")
        
    parts.append("\nPROJECTS")
    projects_lookup = {p["id"]: p for p in master_profile.get("projects", [])}
    for proj in tailor_json.get("projects", []):
        proj_data = projects_lookup.get(proj["project_id"])
        if not proj_data:
            continue
        parts.append(f"{proj_data.get('name', proj['project_id'])}")
        bullets_lookup = {b["id"]: b for b in proj_data.get("bullets", [])}
        for b in proj.get("bullets", []):
            b_data = bullets_lookup.get(b["bullet_id"])
            if not b_data:
                continue
            tier = b["phrasing_tier"]
            text = b_data.get("phrasings", {}).get(tier, "")
            parts.append(f"- {text}")

    parts.append("\nEXPERIENCE")
    exp_lookup = {e["id"]: e for e in master_profile.get("experience", [])}
    for exp in tailor_json.get("experience", []):
        exp_data = exp_lookup.get(exp["experience_id"])
        if not exp_data:
            continue
        parts.append(f"{exp_data.get('name', exp['experience_id'])}")
        bullets_lookup = {b["id"]: b for b in exp_data.get("bullets", [])}
        for b in exp.get("bullets", []):
            b_data = bullets_lookup.get(b["bullet_id"])
            if not b_data:
                continue
            tier = b["phrasing_tier"]
            text = b_data.get("phrasings", {}).get(tier, "")
            parts.append(f"- {text}")

    return "\n".join(parts)

def derive_change_list(base_variant_name: str, tailor_json: dict, master_profile: dict) -> list[dict]:
    """Derive the change list (location, before, after, jd phrase) between the chosen base variant and the tailored output."""
    changes = []
    
    base_variant = master_profile.get("base_variants", {}).get(base_variant_name, {})
    
    # Check skills
    # Since skills aren't explicitly inside base_variant (they're global in master_profile),
    # we just diff against global skills. But let's assume we want to record skills changes.
    base_skills = master_profile.get("skills", {})
    tailored_skills = tailor_json.get("skills", {})
    if base_skills != tailored_skills:
        changes.append({
            "location": "skills",
            "before": str(base_skills),
            "after": str(tailored_skills),
            "jd_phrase": "General Skills Update"
        })
        
    # Check projects
    base_projects = base_variant.get("projects", [])
    tailored_projects = [p["project_id"] for p in tailor_json.get("projects", [])]
    if base_projects != tailored_projects:
        changes.append({
            "location": "projects",
            "before": ", ".join(base_projects),
            "after": ", ".join(tailored_projects),
            "jd_phrase": "Project swap/reorder"
        })
        
    # Check bullets within projects
    base_bullet_order = base_variant.get("bullet_order", [])
    for proj in tailor_json.get("projects", []):
        proj_id = proj["project_id"]
        # For a granular diff, we just want to flag if a bullet was included, omitted, or tier changed.
        # It's sufficient to list the final bullet selection vs the base bullet selection for that project.
        base_bullets = [b for b in base_bullet_order if b.startswith(proj_id)] # crude approximation, but better to compare against default phrasing?
        # Actually the spec just requires location/before/after/jd_phrase.
        # We can just record if the bullet selection changed.
        tailored_bullets = []
        jd_phrases = []
        for b in proj.get("bullets", []):
            tailored_bullets.append(f"{b['bullet_id']} ({b['phrasing_tier']})")
            if "motivating_jd_quote" in b:
                jd_phrases.append(b["motivating_jd_quote"])
        
        # We can't perfectly reconstruct the "before" state of phrasing_tiers unless it's in the base variant.
        # But for the change list, this is fine.
        changes.append({
            "location": f"projects.{proj_id}",
            "before": "default base variant order",
            "after": ", ".join(tailored_bullets),
            "jd_phrase": "; ".join(jd_phrases)
        })

    return changes

import json
import subprocess
from typing import Tuple, Dict, Any, List
from src.tailor.lint import (
    check_wording_budget, check_skills_do_not_claim, check_selection_budget,
    check_experience_immutable, check_flagship_ordering, check_blocked_claims,
    check_keyword_frequency, check_dual_placement
)
from src import audit_schema

# Note: this will need tailoring projection data, but we can abstract it here.
def _extract_json_from_output(raw_output: str) -> dict:
    # A simple parser for JSON wrapped in markdown fences
    try:
        import re
        match = re.search(r'```json\s*(.*?)\s*```', raw_output, re.DOTALL)
        if match:
            return json.loads(match.group(1))
        return json.loads(raw_output)
    except json.JSONDecodeError:
        return {}

def run_tailor(jd_text: str, master_profile: dict, tailored_schema: dict) -> Tuple[list[str], dict, str, list[dict]]:
    """Runs the S1->S3 tailor orchestration and linting."""
    
    # Mocking prompt for now
    prompt = f"JD: {jd_text}\nMaster Profile: {json.dumps(master_profile)}\nGenerate tailored resume matching tailored_schema.json."
    
    result = subprocess.run(["claude", "-p", prompt], capture_output=True, text=True)
    raw_output = result.stdout
    
    tailor_json = _extract_json_from_output(raw_output)
    
    errors = audit_schema.validate(tailor_json, tailored_schema)
    if errors:
        return errors, tailor_json, "", []
        
    base_variant = master_profile.get("base_variants", {}).get(tailor_json["base_variant"], {})
    
    # Run Gate 1 Lints
    lint_errors = []
    
    # Wording & DNC
    base_skills = master_profile.get("skills", {})
    base_skills_text = " ".join(item for items in base_skills.values() for item in items)
    tailored_skills_text = " ".join(item for items in tailor_json.get("skills", {}).values() for item in items)
    
    if check_wording_budget(base_skills_text, tailored_skills_text) > 0.15:
        lint_errors.append("Wording budget exceeded 15% on skills")
        
    lint_errors.extend(check_skills_do_not_claim(tailor_json.get("skills", {}), master_profile.get("do_not_claim", [])))
    
    # Selection & Structural
    lint_errors.extend(check_selection_budget(base_variant.get("projects", []), [p["project_id"] for p in tailor_json.get("projects", [])]))
    
    base_exp_ids = [e["id"] for e in master_profile.get("experience", [])]
    tailored_exp_ids = [e["experience_id"] for e in tailor_json.get("experience", [])]
    lint_errors.extend(check_experience_immutable(base_exp_ids, tailored_exp_ids))
    
    # Extract bullets
    tailored_bullets = []
    for p in tailor_json.get("projects", []) + tailor_json.get("experience", []):
        tailored_bullets.extend(b["bullet_id"] for b in p.get("bullets", []))
        
    # priorities & claim types would need lookup from master profile. Mocked for logic:
    priorities = {}
    claim_types = {}
    for proj in master_profile.get("projects", []) + master_profile.get("experience", []):
        for b in proj.get("bullets", []):
            priorities[b["id"]] = b.get("priority", 4)
            claim_types[b["id"]] = b.get("claim_type", "verified")
            
    lint_errors.extend(check_flagship_ordering(tailored_bullets, priorities))
    lint_errors.extend(check_blocked_claims(tailored_bullets, claim_types))
    
    # Hydration
    hydrated = hydrate_tailor_draft(tailor_json, master_profile)
    
    # Countable JD rules
    # In a real impl, we'd extract keywords from JD.
    # lint_errors.extend(check_keyword_frequency(hydrated, jd_keywords))
    # lint_errors.extend(check_dual_placement(must_have_keywords, tailor_json.get("skills", {}), hydrated_bullets_text))

    change_list = derive_change_list(tailor_json["base_variant"], tailor_json, master_profile)
    
    return lint_errors, tailor_json, hydrated, change_list

def run_critic(hydrated_text: str, jd_text: str, banned_words: str, taste: str) -> dict:
    """Runs the Gate 2 Critic Pass."""
    prompt = f"JD: {jd_text}\nBanned: {banned_words}\nTaste: {taste}\nResume:\n{hydrated_text}\nCritique against R1, R2, R6."
    
    result = subprocess.run(["claude", "-p", prompt], capture_output=True, text=True)
    return _extract_json_from_output(result.stdout)

def tailor_loop(jd_text: str, master_profile: dict, tailored_schema: dict, banned_words: str, taste: str):
    """Orchestrates max 2 revision rounds between the Tailor and Critic."""
    max_rounds = 2
    for round_num in range(max_rounds):
        lint_errors, tailor_json, hydrated, change_list = run_tailor(jd_text, master_profile, tailored_schema)
        if lint_errors:
            # Re-prompt with lint errors in a real system. Here we break or return.
            return {"status": "lint_failed", "errors": lint_errors}
            
        critic_res = run_critic(hydrated, jd_text, banned_words, taste)
        if critic_res.get("verdict") == "pass":
            return {"status": "success", "draft": hydrated, "changes": change_list}
            
        # Re-prompt tailor with critic issues (omitted for brevity)
        
    return {"status": "escalated_to_user", "draft": hydrated, "critic_res": critic_res}
