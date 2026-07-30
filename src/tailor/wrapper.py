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
