"""Synthetic feedback forms for M8P-6. No model, no network, no DB."""
import yaml

BASE = {
    "schema_version": "m8p6.feedback_record.v1",
    "job_id": 225,
    "alignment_fingerprint": "fp0123456789ab",
    "reviewed_at": "2026-08-24",
    "accept": "accept",
    "would_submit": "yes",
    "needs_another_revision": "no",
    "company_alignment": 3,
    "visual_quality": 3,
    "bullet_feedback": [{"bullet_id": "b1", "verdict": "keep", "comment": ""}],
    "missing_skills": [],
    "overemphasized_skills": [],
    "unsupported_claims": [],
    "free_form": "",
}


def form(**overrides) -> str:
    data = {**BASE, **overrides}
    return yaml.safe_dump(data, sort_keys=False)
