import json
import tempfile
from pathlib import Path
from pydantic import ValidationError

from src.profile import MasterProfile, Bullet
from src.tailor.invoke import invoke_text_model, DEFAULT_CLAUDE_CMD
from src.llm_tailor.schemas import DraftResponse, AuditResponse, RepairResponse
from src.llm_tailor.normalization import split_jd_into_spans
from src.llm_tailor.validators import (
    validate_quote_substring, validate_source_span_id, validate_evidence_ids,
    validate_no_do_not_claim, validate_numeric_tokens, validate_amdocs_accounting,
    validate_audit_completeness, validate_colon_semicolon, validate_am_b04_mandatory,
    validate_audit_integrity
)
from src.llm_trace import write_trace

class LaneHalted(Exception):
    pass

class LLMTailorLane:
    def __init__(self, profile: MasterProfile, trace_dir: Path, claude_cmd: tuple[str, ...] = DEFAULT_CLAUDE_CMD):
        self.profile = profile
        self.trace_dir = trace_dir
        self.claude_cmd = claude_cmd

    def _get_evidence_catalog(self) -> str:
        lines = ["# Evidence Catalog\n"]
        for entry in self.profile.experience + self.profile.projects:
            lines.append(f"## {entry.id} ({type(entry).__name__})")
            for b in entry.bullets:
                lines.append(f"ID: {b.id}")
                lines.append(f"Text: {b.phrasings.medium or b.phrasings.short}")
                if b.evidence:
                    lines.append(f"Evidence: {' | '.join(b.evidence)}")
                lines.append("")
        return "\n".join(lines)

    def _extract_json(self, text: str) -> str:
        text = text.strip()
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        return text.strip()

    def _invoke_with_trace(self, prompt: str, invocation_type: str, run_id: str) -> str:
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write(prompt)
            prompt_path = Path(f.name)
            
        result = invoke_text_model(prompt, claude_cmd=self.claude_cmd)
        
        write_trace(
            invocation_type=invocation_type,
            input_paths=[],
            raw_output=result.raw_stdout,
            prompt_path=prompt_path,
            model=result.model,
            trace_dir=self.trace_dir
        )
        prompt_path.unlink()
        
        return result.raw_stdout

    def run_draft(self, jd_text: str, run_id: str) -> DraftResponse:
        spans = split_jd_into_spans(jd_text)
        
        prompt = (
            "You are an expert resume writer. Your task is to draft a tailored resume.\n\n"
            "## 1. JD Spans\n"
        )
        for sid, stext in spans.items():
            prompt += f"[{sid}] {stext}\n"
            
        prompt += "\n" + self._get_evidence_catalog()
        prompt += (
            "\n## Instructions\n"
            "1. Read the JD spans and identify key requirements (both must_have and nice_to_have).\n"
            "2. Select bullets from the Evidence Catalog that best demonstrate these requirements.\n"
            "   - am_b04_data_retention is MANDATORY. Map it to efficiency/reliability (e.g., jd_003).\n"
            "   - Prioritize int_b9 over int_b13 based on evidence strength. Do not drop int_b9 just to cover keyword 'caching' with int_b13.\n"
            "3. Draft continuous, coherent bullets using compressed STAR/XYZ logic. DO NOT use colon-led fragments or semicolon chains.\n"
            "   - Do not invent numbers, domains, or claims not present in canonical evidence.\n"
            "   - For am_b00_order_management_domain: Let the CI/CD clause stand on its own. DO NOT graft JD phrases like 'core platform components' if they aren't in the canonical evidence.\n"
            "   - For int_b10: Tighten to the strongest single mechanism with its guarantee (max 30 words). Avoid architecture dumps.\n"
            "   - For int_b2: Use the exact phrase 'zero 5xx' instead of 'zero server errors'.\n"
            "4. Account for EVERY evidence ID from Amdocs and MalyTech (either select it, or provide an omission rationale in `omitted_evidence_ids`).\n"
            "5. Return a valid JSON object matching this schema:\n"
            "{\n"
            '  "requirements": [{"id": "r1", "source_span_id": "jd_001", "quote": "exact substring of span", "requirement": "desc", "importance": "must_have", "evidence_ids": ["am_b01_dlq_consolidation"]}],\n'
            '  "bullets": [{"id": "am_b01_dlq_consolidation", "entry_id": "amdocs_software_developer", "section": "experience", "text": "Drafted bullet text...", "supported_requirement_ids": ["r1"], "evidence_ids": ["am_b01_dlq_consolidation"]}],\n'
            '  "omitted_evidence_ids": {"am_b02_row_level_entitlement": "Rationale for omission..."}\n'
            "}\n"
            "Output ONLY the JSON object. No other text."
        )
        
        raw_output = self._invoke_with_trace(prompt, "llm_draft", run_id)
        
        try:
            return DraftResponse.model_validate_json(self._extract_json(raw_output))
        except Exception as e:
            raise

    def run_audit(self, jd_text: str, draft: DraftResponse, run_id: str) -> AuditResponse:
        spans = split_jd_into_spans(jd_text)
        
        prompt = "You are an independent resume critic. Evaluate the drafted bullets against the JD and the original evidence.\n\n## JD Spans\n"
        for sid, stext in spans.items():
            prompt += f"[{sid}] {stext}\n"
            
        prompt += "\n## Drafted Bullets & Original Canonical Evidence\n"
        for i, b in enumerate(draft.bullets):
            prompt += f"Index: {i}\nID: {b.id}\nDrafted Text: {b.text}\n"
            ev_text = []
            for eid in b.evidence_ids:
                for entry in self.profile.experience + self.profile.projects:
                    for eb in entry.bullets:
                        if eb.id == eid:
                            ev_text.append(eb.phrasings.medium or eb.phrasings.short)
            prompt += f"Canonical Evidence: {' | '.join(ev_text)}\n\n"
            
        prompt += (
            "\n## Instructions\n"
            "Evaluate each bullet for:\n"
            "- Fidelity (no invented numbers/claims beyond canonical evidence)\n"
            "- Coherence (no colon-led fragments, no semicolon chains)\n"
            "- Relevance (aligns with JD)\n"
            "- Readability (reads naturally)\n"
            "Return a valid JSON object matching this schema:\n"
            "{\n"
            '  "results": [\n'
            '    {"index": 0, "evidence_ids": ["..."], "supported_claims": ["..."], "unsupported_claims": [], "metric_fidelity": "ok", "technology_fidelity": "ok", "ownership_fidelity": "ok", "relevance": 3, "coherence": 3, "readability": 3, "repair_required": false, "reason": "Reason <=200 chars"}\n'
            "  ]\n"
            "}\n"
            "Note: `repair_required` must be true if any fidelity field is not 'ok', if there are any unsupported claims, or if any score (relevance, coherence, readability) is 1. Maximum reason length is 200 chars.\n"
            "CRITICAL: For metric_fidelity and technology_fidelity, you MUST output exactly one of these strings: 'ok', 'altered', or 'invented'. DO NOT output 'unsupported' or anything else. For ownership_fidelity, you MUST output exactly 'ok' or 'overstated'.\n"
            "Ensure exactly one result per drafted bullet. Output ONLY the JSON object. No other text."
        )
        
        raw_output = self._invoke_with_trace(prompt, "llm_audit", run_id)
        
        try:
            return AuditResponse.model_validate_json(self._extract_json(raw_output))
        except Exception as e:
            raise

    def run_repair(self, draft: DraftResponse, audit: AuditResponse, run_id: str) -> RepairResponse:
        prompt = "Repair the rejected bullets based on the audit feedback.\n\n"
        
        for res in audit.results:
            if res.repair_required:
                b = draft.bullets[res.index]
                prompt += f"Bullet ID: {b.id}\nCurrent Text: {b.text}\nReason: {res.reason}\n\n"
                
        prompt += (
            "Return a JSON object replacing ONLY the text of the rejected bullets:\n"
            "{\n"
            '  "repaired_bullets": [\n'
            '    {"id": "bullet_id", "text": "Repaired text..."}\n'
            "  ]\n"
            "}\n"
            "Output ONLY the JSON object. No other text."
        )
        
        raw_output = self._invoke_with_trace(prompt, "llm_repair", run_id)
        
        try:
            return RepairResponse.model_validate_json(self._extract_json(raw_output))
        except Exception as e:
            raise

    def run_reaudit(self, jd_text: str, repaired: list, run_id: str) -> AuditResponse:
        spans = split_jd_into_spans(jd_text)
        prompt = "Re-audit these repaired bullets.\n\n"
        for b in repaired:
            prompt += f"ID: {b.id}\nText: {b.text}\n\n"
            
        prompt += (
            "Return an AuditResponse JSON.\n"
            "{\n"
            '  "results": [\n'
            '    {"index": 0, "evidence_ids": ["..."], "supported_claims": ["..."], "unsupported_claims": [], "metric_fidelity": "ok", "technology_fidelity": "ok", "ownership_fidelity": "ok", "relevance": 3, "coherence": 3, "readability": 3, "repair_required": false, "reason": "Reason <=200 chars"}\n'
            "  ]\n"
            "}\n"
            "Note: `repair_required` must be true if any fidelity field is not 'ok', if there are any unsupported claims, or if any score (relevance, coherence, readability) is 1. Maximum reason length is 200 chars.\n"
            "CRITICAL: For metric_fidelity and technology_fidelity, you MUST output exactly one of these strings: 'ok', 'altered', or 'invented'. DO NOT output 'unsupported' or anything else. For ownership_fidelity, you MUST output exactly 'ok' or 'overstated'.\n"
            "Output ONLY the JSON object. No other text."
        )
        
        raw_output = self._invoke_with_trace(prompt, "llm_reaudit", run_id)
        
        try:
            return AuditResponse.model_validate_json(self._extract_json(raw_output))
        except Exception as e:
            raise

    def enforce_deterministic_validators(self, draft: DraftResponse, jd_text: str):
        spans = split_jd_into_spans(jd_text)
        violations = []
        
        for req in draft.requirements:
            err = validate_source_span_id(req.source_span_id, spans)
            if err: violations.append(err)
            else:
                if not validate_quote_substring(req.quote, spans[req.source_span_id]):
                    violations.append(f"Quote {req.quote!r} not a substring of span {req.source_span_id}")
            violations.extend(validate_evidence_ids(req.evidence_ids, self.profile))
            
        draft_evidence = set()
        for b in draft.bullets:
            violations.extend(validate_evidence_ids(b.evidence_ids, self.profile))
            violations.extend(validate_no_do_not_claim(b.text, self.profile))
            violations.extend(validate_numeric_tokens(b.text, b.evidence_ids, self.profile))
            violations.extend(validate_colon_semicolon(b.text))
            draft_evidence.update(b.evidence_ids)
            
        violations.extend(validate_amdocs_accounting(draft_evidence, set(draft.omitted_evidence_ids.keys())))
        violations.extend(validate_am_b04_mandatory([b.id for b in draft.bullets]))
        
        if violations:
            raise LaneHalted("Deterministic validation failed:\n" + "\n".join(violations))
