"""Privacy-minimised, structural master-profile projections."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.profile import BLOCKED_CLAIM_TYPES, ClaimType

from src.profile import MasterProfile


def _norm(value: str) -> str:
    return " ".join(value.casefold().split())


class ProfileViewError(ValueError):
    pass


@dataclass(frozen=True)
class PositioningEntry:
    id: str
    kind: str
    label: str
    summary: str
    keywords_exact: tuple[str, ...]
    keywords_topical: tuple[str, ...]


@dataclass(frozen=True)
class PositioningView:
    projects: tuple[PositioningEntry, ...]
    experiences: tuple[PositioningEntry, ...]


@dataclass(frozen=True)
class SelectionEntry:
    id: str
    kind: str
    label: str
    keywords_exact: tuple[str, ...]
    keywords_topical: tuple[str, ...]


@dataclass(frozen=True)
class SelectionBullet:
    id: str
    owner_id: str
    owner_kind: str
    priority: int
    claim_type: str
    keywords_hit: tuple[str, ...]


@dataclass(frozen=True)
class SelectionVariant:
    name: str
    projects: tuple[str, ...]
    bullet_order: tuple[str, ...]
    experience_order: tuple[str, ...]
    experience_bullet_counts: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class SelectionCatalog:
    recommended_base_variant: str
    variants: tuple[SelectionVariant, ...]
    projects: tuple[SelectionEntry, ...]
    experiences: tuple[SelectionEntry, ...]
    bullets: tuple[SelectionBullet, ...]
    do_not_claim: tuple[str, ...]
    assumed_baseline_terms: tuple[str, ...]


def positioning_from_profile(profile: MasterProfile) -> PositioningView:
    return PositioningView(
        projects=tuple(PositioningEntry(p.id, "project", p.display_title, p.display_title, p.keywords_exact, p.keywords_topical) for p in profile.projects),
        experiences=tuple(PositioningEntry(e.id, "experience", f"{e.employer} — {e.title}", e.scope_line, e.keywords_exact, e.keywords_topical) for e in profile.experience),
    )


def selection_from_profile(profile: MasterProfile, recommended_base_variant: str) -> SelectionCatalog:
    if recommended_base_variant not in profile.base_variants:
        raise ProfileViewError(f"unknown recommended base variant: {recommended_base_variant!r}")
    project_ids = {p.id for p in profile.projects}
    experience_ids = {e.id for e in profile.experience}
    bullet_owner: dict[str, tuple[str, str]] = {}
    bullets: list[SelectionBullet] = []
    for entry in (*profile.projects, *profile.experience):
        kind = "project" if entry.id in project_ids else "experience"
        for bullet in entry.bullets:
            bullet_owner[bullet.id] = (entry.id, kind)
            if not bullet.is_blocked:
                bullets.append(SelectionBullet(bullet.id, entry.id, kind, bullet.priority, bullet.claim_type.value, bullet.keywords_hit))
    variants = []
    for name, base in profile.base_variants.items():
        counts: list[tuple[str, int]] = []
        order: list[str] = []
        for bid in base.bullet_order:
            owner_id, owner_kind = bullet_owner[bid]
            if owner_kind == "experience":
                if owner_id not in order:
                    order.append(owner_id)
                    counts.append((owner_id, 0))
                counts[-1] = (owner_id, counts[-1][1] + 1)
        variants.append(SelectionVariant(name, base.projects, base.bullet_order, tuple(order), tuple(counts)))
    return SelectionCatalog(
        recommended_base_variant=recommended_base_variant,
        variants=tuple(variants),
        projects=tuple(SelectionEntry(p.id, "project", p.display_title, p.keywords_exact, p.keywords_topical) for p in profile.projects),
        experiences=tuple(SelectionEntry(e.id, "experience", f"{e.employer} — {e.title}", e.keywords_exact, e.keywords_topical) for e in profile.experience),
        bullets=tuple(bullets),
        do_not_claim=profile.do_not_claim,
        assumed_baseline_terms=(),
    )


def positioning_to_dict(view: PositioningView) -> dict[str, Any]:
    def entry(e: PositioningEntry) -> dict[str, Any]:
        return {"id": e.id, "kind": e.kind, "label": e.label, "summary": e.summary, "keywords_exact": list(e.keywords_exact), "keywords_topical": list(e.keywords_topical)}
    return {"projects": [entry(e) for e in view.projects], "experiences": [entry(e) for e in view.experiences]}


def selection_to_dict(catalog: SelectionCatalog) -> dict[str, Any]:
    return {
        "recommended_base_variant": catalog.recommended_base_variant,
        "variants": [{"name": v.name, "projects": list(v.projects), "bullet_order": list(v.bullet_order), "experience_order": list(v.experience_order), "experience_bullet_counts": [[k, n] for k, n in v.experience_bullet_counts]} for v in catalog.variants],
        "projects": [_selection_entry(e) for e in catalog.projects],
        "experiences": [_selection_entry(e) for e in catalog.experiences],
        "bullets": [{"id": b.id, "owner_id": b.owner_id, "owner_kind": b.owner_kind, "priority": b.priority, "claim_type": b.claim_type, "keywords_hit": list(b.keywords_hit)} for b in catalog.bullets],
        "do_not_claim": list(catalog.do_not_claim),
        "assumed_baseline_terms": list(catalog.assumed_baseline_terms),
    }


def _selection_entry(e: SelectionEntry) -> dict[str, Any]:
    return {"id": e.id, "kind": e.kind, "label": e.label, "keywords_exact": list(e.keywords_exact), "keywords_topical": list(e.keywords_topical)}


def _obj(value: object, keys: set[str], path: str) -> dict[str, Any]:
    if not isinstance(value, dict): raise ProfileViewError(f"{path}: expected object")
    if set(value) != keys: raise ProfileViewError(f"{path}: fields must be {sorted(keys)}")
    return value


def _str(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip(): raise ProfileViewError(f"{path}: expected nonempty string")
    return value


def _strings(value: object, path: str, *, nonempty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list) or (nonempty and not value): raise ProfileViewError(f"{path}: expected list")
    result = tuple(_str(item, f"{path}[]") for item in value)
    if len({_norm(item) for item in result}) != len(result): raise ProfileViewError(f"{path}: duplicate values")
    return result


def _parse_entries(raw: object, path: str, positioning: bool) -> tuple:
    if not isinstance(raw, list): raise ProfileViewError(f"{path}: expected list")
    result = []
    seen: set[str] = set()
    for i, value in enumerate(raw):
        keys = {"id", "kind", "label", "summary", "keywords_exact", "keywords_topical"} if positioning else {"id", "kind", "label", "keywords_exact", "keywords_topical"}
        o = _obj(value, keys, f"{path}[{i}]")
        ident = _str(o["id"], f"{path}[{i}].id")
        if ident in seen: raise ProfileViewError(f"{path}: duplicate id {ident}")
        seen.add(ident)
        kind = _str(o["kind"], f"{path}[{i}].kind")
        if kind not in ("project", "experience"): raise ProfileViewError(f"{path}: invalid kind")
        if positioning: result.append(PositioningEntry(ident, kind, _str(o["label"], "label"), _str(o["summary"], "summary"), _strings(o["keywords_exact"], "exact"), _strings(o["keywords_topical"], "topical")))
        else: result.append(SelectionEntry(ident, kind, _str(o["label"], "label"), _strings(o["keywords_exact"], "exact"), _strings(o["keywords_topical"], "topical")))
    return tuple(result)


def parse_positioning(raw: dict[str, Any]) -> PositioningView:
    o = _obj(raw, {"projects", "experiences"}, "$")
    projects = _parse_entries(o["projects"], "$.projects", True)
    experiences = _parse_entries(o["experiences"], "$.experiences", True)
    if any(e.kind != "project" for e in projects) or any(e.kind != "experience" for e in experiences): raise ProfileViewError("positioning entry kind mismatch")
    return PositioningView(projects, experiences)


def parse_selection(raw: dict[str, Any]) -> SelectionCatalog:
    o = _obj(raw, {"recommended_base_variant", "variants", "projects", "experiences", "bullets", "do_not_claim", "assumed_baseline_terms"}, "$")
    recommended = _str(o["recommended_base_variant"], "$.recommended_base_variant")
    projects = _parse_entries(o["projects"], "$.projects", False)
    experiences = _parse_entries(o["experiences"], "$.experiences", False)
    all_entries = (*projects, *experiences)
    if len({e.id for e in all_entries}) != len(all_entries):
        raise ProfileViewError("project and experience ids must be globally unique")
    if any(e.kind != "project" for e in projects) or any(e.kind != "experience" for e in experiences):
        raise ProfileViewError("entry kind does not match its collection")
    by_owner = {e.id: e.kind for e in all_entries}
    bullets = []
    seen = set()
    if not isinstance(o["bullets"], list): raise ProfileViewError("$.bullets: expected list")
    for i, value in enumerate(o["bullets"]):
        b = _obj(value, {"id", "owner_id", "owner_kind", "priority", "claim_type", "keywords_hit"}, f"$.bullets[{i}]")
        ident = _str(b["id"], "bullet.id")
        if ident in seen: raise ProfileViewError("duplicate bullet id")
        seen.add(ident)
        if b["owner_id"] not in by_owner or b["owner_kind"] != by_owner[b["owner_id"]]: raise ProfileViewError("unknown bullet owner")
        if isinstance(b["priority"], bool) or not isinstance(b["priority"], int) or b["priority"] < 1: raise ProfileViewError("invalid bullet priority")
        claim = _str(b["claim_type"], "claim_type")
        if claim not in {member.value for member in ClaimType}:
            raise ProfileViewError("unknown claim type")
        if claim in {member.value for member in BLOCKED_CLAIM_TYPES}:
            raise ProfileViewError("blocked bullet present")
        bullets.append(SelectionBullet(ident, b["owner_id"], b["owner_kind"], b["priority"], claim, _strings(b["keywords_hit"], "keywords_hit")))
    if not isinstance(o["variants"], list): raise ProfileViewError("$.variants: expected list")
    variants = []
    variant_names: set[str] = set()
    bullet_by_id = {bullet.id: bullet for bullet in bullets}
    project_ids = {entry.id for entry in projects}
    experience_ids = {entry.id for entry in experiences}
    for i, value in enumerate(o["variants"]):
        v = _obj(value, {"name", "projects", "bullet_order", "experience_order", "experience_bullet_counts"}, f"$.variants[{i}]")
        counts_raw = v["experience_bullet_counts"]
        if not isinstance(counts_raw, list): raise ProfileViewError("invalid experience counts")
        name = _str(v["name"], "variant.name")
        if name in variant_names:
            raise ProfileViewError("duplicate variant name")
        variant_names.add(name)
        projects_order = _strings(v["projects"], "projects")
        if any(project not in project_ids for project in projects_order):
            raise ProfileViewError("variant references unknown project")
        bullet_order = _strings(v["bullet_order"], "bullet_order", nonempty=True)
        if any(bullet_id not in bullet_by_id for bullet_id in bullet_order):
            raise ProfileViewError("variant references unknown bullet")
        counts = []
        for pair in counts_raw:
            if not isinstance(pair, list) or len(pair) != 2 or not isinstance(pair[1], int) or isinstance(pair[1], bool): raise ProfileViewError("invalid experience count")
            owner = _str(pair[0], "experience id")
            if owner not in experience_ids:
                raise ProfileViewError("variant references unknown experience")
            if any(existing == owner for existing, _ in counts):
                raise ProfileViewError("duplicate experience-count owner")
            if pair[1] <= 0:
                raise ProfileViewError("experience count must be positive")
            counts.append((owner, pair[1]))
        derived_order: list[str] = []
        derived_counts: list[tuple[str, int]] = []
        active_owner: str | None = None
        closed_experiences: set[str] = set()
        for bullet_id in bullet_order:
            bullet = bullet_by_id[bullet_id]
            if bullet.owner_kind == "experience":
                owner = bullet.owner_id
                if owner != active_owner:
                    if owner in closed_experiences:
                        raise ProfileViewError("experience owner appears in disjoint groups")
                    if active_owner is not None:
                        closed_experiences.add(active_owner)
                    active_owner = owner
                    derived_order.append(owner)
                    derived_counts.append((owner, 0))
                derived_counts[-1] = (owner, derived_counts[-1][1] + 1)
        stored_order = _strings(v["experience_order"], "experience_order")
        if tuple(stored_order) != tuple(derived_order) or tuple(counts) != tuple(derived_counts):
            raise ProfileViewError("stored experience order/counts disagree with bullet order")
        selected_projects = set(projects_order)
        for bullet_id in bullet_order:
            bullet = bullet_by_id[bullet_id]
            if bullet.owner_kind == "project" and bullet.owner_id not in selected_projects:
                raise ProfileViewError("variant contains bullet from unselected project")
        variants.append(SelectionVariant(name, projects_order, bullet_order, tuple(stored_order), tuple(counts)))
    if not any(v.name == recommended for v in variants): raise ProfileViewError("recommended variant is unknown")
    return SelectionCatalog(recommended, tuple(variants), projects, experiences, tuple(bullets), _strings(o["do_not_claim"], "do_not_claim"), _strings(o["assumed_baseline_terms"], "assumed_baseline_terms"))


positioning_view_to_dict = positioning_to_dict
parse_positioning_view = parse_positioning
selection_catalog_to_dict = selection_to_dict
parse_selection_catalog = parse_selection
