import difflib
import re

def _normalize_tokens(text: str) -> list[str]:
    """Normalize string (casefold, strip word-edge punctuation, collapse whitespace) and split to tokens."""
    # Strip common punctuation from word edges but keep internal punctuation like C++
    text = text.casefold()
    tokens = text.split()
    normalized = []
    for t in tokens:
        t = t.strip('.,;:"\'()[]{}!?')
        if t:
            normalized.append(t)
    return normalized

def check_wording_budget(base_skills_text: str, tailored_skills_text: str) -> float:
    """Return the wording delta ratio. Must be <= 0.15."""
    base_tokens = _normalize_tokens(base_skills_text)
    tailored_tokens = _normalize_tokens(tailored_skills_text)

    if not base_tokens:
        return 0.0

    matcher = difflib.SequenceMatcher(None, base_tokens, tailored_tokens, autojunk=False)
    distance = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "replace":
            distance += max(i2 - i1, j2 - j1)
        elif tag == "delete":
            distance += (i2 - i1)
        elif tag == "insert":
            distance += (j2 - j1)
            
    return distance / len(base_tokens)

def check_skills_do_not_claim(tailored_skills: dict[str, list[str]], do_not_claim: list[str]) -> list[str]:
    """Return a list of violations if any tailored skill matches a do_not_claim term."""
    violations = []
    normalized_dnc = { _normalize_tokens(term)[0] if _normalize_tokens(term) else term.casefold() : term for term in do_not_claim }
    
    # We want to match any term in do_not_claim against the tailored skills.
    # The normalization should ideally handle multi-word, but let's just use string inclusion or normalized comparison.
    # Actually, the spec says "under normalized comparison".
    dnc_normalized_phrases = { " ".join(_normalize_tokens(term)): term for term in do_not_claim }

    for category, items in tailored_skills.items():
        for item in items:
            item_norm = " ".join(_normalize_tokens(item))
            for dnc_norm, original_dnc in dnc_normalized_phrases.items():
                # If the exact normalized DNC phrase is within the normalized item phrase
                # Or maybe just exact match? "under normalized comparison".
                # Usually skills are exact matches like "Kubernetes". Let's do exact match or inclusion.
                if dnc_norm and dnc_norm in item_norm:
                    violations.append(f"do_not_claim violation: '{original_dnc}' found in skills")

    return violations

def check_selection_budget(base_project_ids: list[str], tailored_project_ids: list[str]) -> list[str]:
    """Ensure <= 1 project swap compared to base variant."""
    base_set = set(base_project_ids)
    tailored_set = set(tailored_project_ids)
    
    # Missing projects (swapped out)
    missing = base_set - tailored_set
    # New projects (swapped in)
    new = tailored_set - base_set
    
    violations = []
    # If the user swapped out more than 1, or swapped in more than 1
    if len(missing) > 1 or len(new) > 1:
        violations.append(f"selection budget exceeded: swapped out {len(missing)} projects, swapped in {len(new)} projects (max 1)")
    
    return violations

def check_experience_immutable(base_exp_ids: list[str], tailored_exp_ids: list[str]) -> list[str]:
    """Verify every experience_id from base variant is present in exactly the same reverse-chronological order."""
    violations = []
    if base_exp_ids != tailored_exp_ids:
        violations.append(f"experience entries are immutable: expected {base_exp_ids}, got {tailored_exp_ids}")
    return violations

def check_flagship_ordering(tailored_bullets: list[str], bullet_priorities: dict[str, int]) -> list[str]:
    """Verify no filler bullet precedes a flagship bullet (priority must monotonically increase or stay same, lower number = higher precedence)."""
    violations = []
    last_priority = 1
    for bid in tailored_bullets:
        priority = bullet_priorities.get(bid, 4)
        if priority < last_priority:
            violations.append(f"flagship ordering violation: bullet {bid} (priority {priority}) placed after a bullet with priority {last_priority}")
        last_priority = max(last_priority, priority)
    return violations

def check_blocked_claims(tailored_bullets: list[str], bullet_claim_types: dict[str, str]) -> list[str]:
    """Reject any bullet_id with a blocked claim_type."""
    blocked_types = {"ownership_unresolved", "needs_input"}
    violations = []
    for bid in tailored_bullets:
        claim = bullet_claim_types.get(bid, "")
        if claim in blocked_types:
            violations.append(f"blocked claim violation: bullet {bid} has blocked claim_type '{claim}'")
    return violations

from collections import Counter

def check_keyword_frequency(hydrated_text: str, jd_keywords: list[str]) -> list[str]:
    """Ensure no JD keyword occurs > 4x in the text."""
    violations = []
    text_norm = " ".join(_normalize_tokens(hydrated_text))
    for keyword in jd_keywords:
        kw_norm = " ".join(_normalize_tokens(keyword))
        if not kw_norm:
            continue
        count = text_norm.count(kw_norm)
        if count > 4:
            violations.append(f"keyword stuffing violation: term '{keyword}' appears {count} times (max 4)")
    return violations

def check_dual_placement(must_have_keywords: list[str], skills_dict: dict[str, list[str]], hydrated_bullets_text: str) -> list[str]:
    """Every must-have keyword must be in skills AND in >= 1 bullet."""
    violations = []
    skills_text = " ".join([item for items in skills_dict.values() for item in items])
    skills_norm = " ".join(_normalize_tokens(skills_text))
    bullets_norm = " ".join(_normalize_tokens(hydrated_bullets_text))
    
    for keyword in must_have_keywords:
        kw_norm = " ".join(_normalize_tokens(keyword))
        if not kw_norm:
            continue
        in_skills = kw_norm in skills_norm
        in_bullets = kw_norm in bullets_norm
        if not (in_skills and in_bullets):
            violations.append(f"dual placement violation: must-have keyword '{keyword}' missing from skills or bullets")
    return violations
