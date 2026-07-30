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
