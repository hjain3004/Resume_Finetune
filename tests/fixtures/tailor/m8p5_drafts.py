"""Synthetic TailoredDraft builders for M8P-5. No model, no network, no DB."""
from src.render.emphasis import parse_emphasis
from src.tailor.s3 import DraftBullet, TailoredDraft


def draft_bullet(bullet_id: str, owner_id: str, owner_kind: str, marked: str) -> DraftBullet:
    plain, spans = parse_emphasis(marked)
    return DraftBullet(bullet_id=bullet_id, owner_id=owner_id, owner_kind=owner_kind,
                       text=marked, plain_text=plain, emphasis=spans)


def make_draft(*, bullets, project_ids, experience_ids, skills,
               fingerprint="fp", base_variant="backend") -> TailoredDraft:
    return TailoredDraft(job_id=1, company="Acme", title="SWE",
                         base_variant=base_variant, project_ids=tuple(project_ids),
                         experience_ids=tuple(experience_ids), bullets=tuple(bullets),
                         skills=tuple(skills), alignment_fingerprint=fingerprint)
