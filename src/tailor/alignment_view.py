"""Canonical, privacy-minimised source projection for constrained S3."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from src.profile import BLOCKED_CLAIM_TYPES, MasterProfile
from src.render.emphasis import EmphasisError, parse_emphasis
from src.render.mapping import default_phrasing_text
from src.tailor.s2 import S2Request, S2Response, validate_s2_selection


class AlignmentError(ValueError):
    """Raised when a canonical alignment projection cannot be built or parsed."""


@dataclass(frozen=True)
class AlignmentBullet:
    bullet_id: str
    owner_id: str
    owner_kind: str
    source_text: str
    plain_text: str
    emphasis: tuple[tuple[int, int], ...]
    keywords_hit: tuple[str, ...]
    claim_type: str


@dataclass(frozen=True)
class AlignmentView:
    base_variant: str
    project_ids: tuple[str, ...]
    experience_ids: tuple[str, ...]
    bullets: tuple[AlignmentBullet, ...]
    skills: tuple[tuple[str, tuple[str, ...]], ...]
    do_not_claim: tuple[str, ...]
    fingerprint: str


def _canonical_dict(view: AlignmentView) -> dict[str, Any]:
    return {
        "base_variant": view.base_variant,
        "project_ids": list(view.project_ids),
        "experience_ids": list(view.experience_ids),
        "bullets": [
            {
                "bullet_id": bullet.bullet_id,
                "owner_id": bullet.owner_id,
                "owner_kind": bullet.owner_kind,
                "source_text": bullet.source_text,
                "plain_text": bullet.plain_text,
                "emphasis": [[start, end] for start, end in bullet.emphasis],
                "keywords_hit": list(bullet.keywords_hit),
                "claim_type": bullet.claim_type,
            }
            for bullet in view.bullets
        ],
        "skills": [[category, list(items)] for category, items in view.skills],
        "do_not_claim": list(view.do_not_claim),
    }


def _fingerprint(projection: dict[str, Any]) -> str:
    encoded = json.dumps(projection, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def default_alignment_bullet(profile: MasterProfile, bullet_id: str) -> AlignmentBullet:
    index = {
        bullet.id: (entry, bullet)
        for entry in (*profile.projects, *profile.experience)
        for bullet in entry.bullets
    }
    if bullet_id not in index:
        raise AlignmentError(f"unknown bullet id: {bullet_id}")
    entry, bullet = index[bullet_id]
    if bullet.is_blocked or bullet.claim_type in BLOCKED_CLAIM_TYPES:
        raise AlignmentError(f"blocked bullet id: {bullet_id}")
    source_text = default_phrasing_text(bullet)
    try:
        plain_text, emphasis = parse_emphasis(source_text)
    except EmphasisError as exc:
        raise AlignmentError(f"bullet {bullet_id}: invalid emphasis: {exc}") from exc
    owner_kind = "project" if entry in profile.projects else "experience"
    return AlignmentBullet(
        bullet_id=bullet.id,
        owner_id=entry.id,
        owner_kind=owner_kind,
        source_text=source_text,
        plain_text=plain_text,
        emphasis=emphasis,
        keywords_hit=bullet.keywords_hit,
        claim_type=bullet.claim_type.value,
    )


def alignment_from_profile(
    profile: MasterProfile, request: S2Request, response: S2Response
) -> AlignmentView:
    validate_s2_selection(response, request)
    if response.base_variant not in profile.base_variants:
        raise AlignmentError(f"unknown base variant: {response.base_variant}")
    project_ids = tuple(choice.project_id for choice in response.projects)
    experience_ids = tuple(entry.id for entry in profile.experience)
    bullets = tuple(default_alignment_bullet(profile, bullet_id) for bullet_id in response.bullet_order)
    project_set = set(project_ids)
    for bullet in bullets:
        if bullet.owner_kind == "project" and bullet.owner_id not in project_set:
            raise AlignmentError(f"bullet {bullet.bullet_id}: owner is not selected")
    skills = tuple((category, tuple(items)) for category, items in profile.skills.items())
    view_without_fingerprint = AlignmentView(
        base_variant=response.base_variant,
        project_ids=project_ids,
        experience_ids=experience_ids,
        bullets=bullets,
        skills=skills,
        do_not_claim=profile.do_not_claim,
        fingerprint="",
    )
    return AlignmentView(**{**view_without_fingerprint.__dict__, "fingerprint": _fingerprint(_canonical_dict(view_without_fingerprint))})


def alignment_to_dict(view: AlignmentView) -> dict[str, Any]:
    projection = _canonical_dict(view)
    projection["fingerprint"] = view.fingerprint
    return projection


def parse_alignment(raw: object) -> AlignmentView:
    if not isinstance(raw, dict):
        raise AlignmentError("$: expected object")
    fields = {"base_variant", "project_ids", "experience_ids", "bullets", "skills", "do_not_claim", "fingerprint"}
    if set(raw) != fields:
        raise AlignmentError("$: unexpected or missing fields")
    if not isinstance(raw["base_variant"], str) or not raw["base_variant"].strip():
        raise AlignmentError("$.base_variant: expected nonempty string")

    def strings(value: object, path: str) -> tuple[str, ...]:
        if not isinstance(value, list) or not value or any(not isinstance(item, str) or not item.strip() for item in value):
            raise AlignmentError(f"{path}: expected nonempty string array")
        result = tuple(value)
        if len(set(result)) != len(result):
            raise AlignmentError(f"{path}: duplicate values")
        return result

    project_ids = strings(raw["project_ids"], "$.project_ids")
    experience_ids = strings(raw["experience_ids"], "$.experience_ids")
    if not isinstance(raw["bullets"], list) or not raw["bullets"]:
        raise AlignmentError("$.bullets: expected nonempty array")
    bullets = []
    seen: set[str] = set()
    bullet_fields = {"bullet_id", "owner_id", "owner_kind", "source_text", "plain_text", "emphasis", "keywords_hit", "claim_type"}
    for index, item in enumerate(raw["bullets"]):
        if not isinstance(item, dict) or set(item) != bullet_fields:
            raise AlignmentError(f"$.bullets[{index}]: unexpected or missing fields")
        bullet_id = item["bullet_id"]
        if not isinstance(bullet_id, str) or not bullet_id.strip() or bullet_id in seen:
            raise AlignmentError(f"$.bullets[{index}].bullet_id: invalid or duplicate id")
        seen.add(bullet_id)
        for key in ("owner_id", "source_text", "plain_text", "claim_type"):
            if not isinstance(item[key], str) or not item[key].strip():
                raise AlignmentError(f"$.bullets[{index}].{key}: expected nonempty string")
        if item["owner_kind"] not in ("project", "experience"):
            raise AlignmentError(f"$.bullets[{index}].owner_kind: invalid kind")
        emphasis = item["emphasis"]
        if not isinstance(emphasis, list) or any(not isinstance(span, list) or len(span) != 2 or any(isinstance(value, bool) or not isinstance(value, int) for value in span) for span in emphasis):
            raise AlignmentError(f"$.bullets[{index}].emphasis: invalid spans")
        keywords_hit = strings(item["keywords_hit"], f"$.bullets[{index}].keywords_hit") if item["keywords_hit"] else ()
        bullets.append(AlignmentBullet(bullet_id, item["owner_id"], item["owner_kind"], item["source_text"], item["plain_text"], tuple((span[0], span[1]) for span in emphasis), keywords_hit, item["claim_type"]))
    if not isinstance(raw["skills"], list):
        raise AlignmentError("$.skills: expected array")
    skills = []
    for index, item in enumerate(raw["skills"]):
        if not isinstance(item, list) or len(item) != 2 or not isinstance(item[0], str) or not item[0].strip():
            raise AlignmentError(f"$.skills[{index}]: invalid entry")
        skills.append((item[0], strings(item[1], f"$.skills[{index}][1]") if item[1] else ()))
    do_not_claim = strings(raw["do_not_claim"], "$.do_not_claim") if raw["do_not_claim"] else ()
    fingerprint = raw["fingerprint"]
    if not isinstance(fingerprint, str) or len(fingerprint) != 64:
        raise AlignmentError("$.fingerprint: invalid fingerprint")
    view = AlignmentView(raw["base_variant"], project_ids, experience_ids, tuple(bullets), tuple(skills), do_not_claim, fingerprint)
    if _fingerprint(_canonical_dict(view)) != fingerprint:
        raise AlignmentError("$.fingerprint: does not match canonical projection")
    return view
