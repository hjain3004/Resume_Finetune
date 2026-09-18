"""LLM-first tailoring lane (Tailor2)."""

from src.tailor2.compatibility import (
    GeneratedBulletCandidate,
    SemanticRequirement,
    TailoredSkills,
    UnusedEvidenceLedger,
    WholeResumeRanking,
    evaluate_whole_resume_ranking,
    generate_and_rank_bullet_candidates,
    parse_atomic_requirements_semantically,
    select_tailored_skills,
)

__all__ = [
    "GeneratedBulletCandidate",
    "SemanticRequirement",
    "TailoredSkills",
    "UnusedEvidenceLedger",
    "WholeResumeRanking",
    "evaluate_whole_resume_ranking",
    "generate_and_rank_bullet_candidates",
    "parse_atomic_requirements_semantically",
    "select_tailored_skills",
]
