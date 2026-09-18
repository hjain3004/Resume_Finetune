import re
from src.profile import MasterProfile
from src.render.parse import ParsedPdf
from src.render.model import RenderDoc
from src.llm_tailor.schemas import DraftResponse, AuditResponse, RepairResponse
from src.llm_tailor.normalization import (
    split_jd_into_spans,
    normalize_quote_for_match,
    extract_digit_sequences,
)

def validate_quote_substring(quote: str, span_text: str) -> bool:
    """True if normalized quote is a substring of normalized span text."""
    nq = normalize_quote_for_match(quote)
    return nq in span_text

def validate_source_span_id(span_id: str, spans: dict[str, str]) -> str | None:
    if span_id not in spans:
        return f"source_span_id {span_id!r} not found in JD spans"
    return None

def validate_evidence_ids(evidence_ids: list[str], profile: MasterProfile) -> list[str]:
    # all possible evidence IDs
    valid_ids = set()
    for entry in profile.experience:
        for b in entry.bullets:
            valid_ids.add(b.id)
    for entry in profile.projects:
        for b in entry.bullets:
            valid_ids.add(b.id)
            
    violations = []
    for eid in evidence_ids:
        if eid not in valid_ids:
            violations.append(f"Evidence ID {eid!r} not found in master profile")
    return violations

def validate_no_do_not_claim(text: str, profile: MasterProfile) -> list[str]:
    violations = []
    text_lower = text.lower()
    for banned in profile.do_not_claim:
        if banned.lower() in text_lower:
            violations.append(f"Text contains banned term: {banned!r}")
    return violations

def validate_numeric_tokens(draft_text: str, evidence_ids: list[str], profile: MasterProfile) -> list[str]:
    # Gather evidence text
    evidence_text = []
    for entry in profile.experience + profile.projects:
        for b in entry.bullets:
            if b.id in evidence_ids:
                # We concatenate long, medium, short phrases
                evidence_text.extend([p for p in (b.phrasings.short, b.phrasings.medium, b.phrasings.long) if p is not None])
    
    canonical_text = " ".join(evidence_text)
    
    draft_digits = extract_digit_sequences(draft_text)
    canonical_digits = extract_digit_sequences(canonical_text)
    
    violations = []
    for d in draft_digits:
        if d not in canonical_digits:
            violations.append(f"Numeric token {d!r} found in draft but not in canonical evidence")
    return violations

def validate_repair_scope(original_bullets: list, repaired_bullets: list) -> list[str]:
    # original_bullets: DraftedBullet
    # repaired_bullets: RepairedBullet
    # We just ensure the repair only changes the text.
    # The actual schema ensures RepairedBullet only has `id` and `text`.
    # We must ensure the returned IDs exactly match the rejected IDs.
    pass

def validate_amdocs_accounting(draft_evidence_ids: set[str], omitted_ids: set[str]) -> list[str]:
    # All 7 Amdocs IDs
    amdocs_ids = {
        "am_b00_order_management_domain",
        "am_b01_dlq_consolidation",
        "am_b02_row_level_entitlement",
        "am_b03_audit_trail",
        "am_b04_data_retention",
        "am_b05_test_automation",
        "am_b06_aws_ci_and_resilience"
    }
    violations = []
    for aid in amdocs_ids:
        in_draft = aid in draft_evidence_ids
        in_omitted = aid in omitted_ids
        if in_draft and in_omitted:
            violations.append(f"Amdocs ID {aid} is both selected and omitted")
        if not in_draft and not in_omitted:
            violations.append(f"Amdocs ID {aid} is neither selected nor omitted")
    return violations

def validate_audit_completeness(draft_bullet_ids: list[str], audit_bullet_ids: list[str]) -> list[str]:
    violations = []
    if draft_bullet_ids != audit_bullet_ids:
        violations.append("Audit bullet IDs do not match draft bullet IDs exactly in number or order")
    return violations

def validate_colon_semicolon(text: str) -> list[str]:
    violations = []
    # Colon-led fragment (starts with colon or early colon followed by space/newline without much before it)
    # The spec specifically means patterns like "Action: did something" or "Role: developer"
    if re.search(r'^[A-Z][a-z]+:\s', text):
        violations.append(f"Text contains colon-led fragment: {text}")
    
    # Semicolon chains
    if text.count(';') >= 2:
        violations.append(f"Text contains semicolon chain (>= 2 semicolons): {text}")
    
    return violations

def validate_page_fill_above_97_percent(parsed: ParsedPdf) -> list[str]:
    """Measured topmost-to-bottommost text extent over page height, > 97%."""
    if not parsed.boxes:
        return ["No text boxes found in PDF"]
        
    topmost = max(box.y1 for box in parsed.boxes)
    bottommost = min(box.y0 for box in parsed.boxes)
    extent = topmost - bottommost
    
    fill_percent = (extent / parsed.page_height) * 100
    if fill_percent < 97.0:
        return [f"Page fill is {fill_percent:.1f}%, must be > 97.0%"]
    return []

def validate_skills_section_not_padded(doc: RenderDoc, profile: MasterProfile) -> list[str]:
    """Measure fill and cap the skills section independently."""
    violations = []
    doc_skills = sum(len(terms) for terms in doc.skills.values())
    prof_skills = sum(len(terms) for terms in profile.skills.values())
    if doc_skills > prof_skills:
        violations.append(f"Skills section was padded: {doc_skills} terms (baseline: {prof_skills})")
    return violations

def validate_am_b04_mandatory(draft_bullet_ids: list[str]) -> list[str]:
    violations = []
    count = draft_bullet_ids.count('am_b04_data_retention')
    if count != 1:
        violations.append(f"am_b04_data_retention must appear exactly once in the drafted bullets, but found {count} times.")
    return violations

def validate_audit_integrity(audit_response) -> list[str]:
    violations = []
    for res in audit_response.results:
        has_issue = (
            res.metric_fidelity != 'ok' or 
            res.technology_fidelity != 'ok' or 
            res.ownership_fidelity != 'ok' or 
            res.relevance == 1 or 
            res.coherence == 1 or 
            res.readability == 1 or
            len(res.unsupported_claims) > 0
        )
        if has_issue and not res.repair_required:
            violations.append(f"Audit index {res.index} has a fidelity/score issue but repair_required is false.")
        if not has_issue and res.repair_required:
            violations.append(f"Audit index {res.index} has repair_required true but no fidelity/score issues.")
        if len(res.reason) > 200:
            violations.append(f"Audit index {res.index} reason exceeds 200 chars.")
    return violations
