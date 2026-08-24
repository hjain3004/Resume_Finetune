"""Strict structural-selection contract and deterministic validator."""
from __future__ import annotations
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any
from src.tailor.profile_views import SelectionCatalog, SelectionBullet, selection_to_dict, parse_selection, PositioningView, PositioningEntry
from src.tailor.s0 import S0Request, S0Response, S0SemanticError, s0_request_to_dict, s0_response_to_dict, parse_s0_request, parse_s0_response
from src.tailor.s1 import S1Response, s1_response_to_dict, parse_s1_response_dict

def _norm(v: str) -> str: return " ".join(v.casefold().split())
class S2ParseError(ValueError): pass
class S2SemanticError(ValueError): pass
class S2ValidationError(ValueError): pass
class CoverageStatus(str, Enum): COVERED = "covered"; GAP = "gap"

@dataclass(frozen=True)
class ProjectChoice:
    project_id: str
    reason: str
    s0_point_indexes: tuple[int, ...]
@dataclass(frozen=True)
class CoverageEntry:
    term: str
    status: str
    bullet_ids: tuple[str, ...]
@dataclass(frozen=True)
class S2Request:
    job_id: int
    company: str
    title: str
    s1: S1Response
    s0: S0Response
    catalog: SelectionCatalog
@dataclass(frozen=True)
class S2Response:
    base_variant: str
    projects: tuple[ProjectChoice, ...]
    bullet_order: tuple[str, ...]
    coverage: tuple[CoverageEntry, ...]
    @property
    def gap_terms(self) -> tuple[str, ...]: return tuple(x.term for x in self.coverage if x.status == CoverageStatus.GAP.value)

def _obj(v: object, fields: set[str], path: str) -> dict:
    if not isinstance(v, dict) or set(v) != fields: raise S2ParseError(f"{path}: invalid fields")
    return v
def _str(v: object, path: str) -> str:
    if not isinstance(v, str) or not v.strip(): raise S2ParseError(f"{path}: expected nonempty string")
    return v
def _strs(v: object, path: str, nonempty: bool = False) -> tuple[str, ...]:
    if not isinstance(v, list) or (nonempty and not v): raise S2ParseError(f"{path}: expected array")
    result = tuple(_str(x, path) for x in v)
    if len(set(result)) != len(result): raise S2ParseError(f"{path}: duplicate values")
    return result

def build_s2_request(job_id: int, company: str, title: str, s1: S1Response, s0: S0Response, catalog: SelectionCatalog) -> S2Request:
    return S2Request(job_id, company, title, s1, s0, catalog)
def s2_request_to_dict(request: S2Request) -> dict[str, Any]:
    return {"job_id": request.job_id, "company": request.company, "title": request.title, "s1": s1_response_to_dict(request.s1), "s0": s0_response_to_dict(request.s0), "catalog": selection_to_dict(request.catalog)}
def parse_s2_request(raw: dict[str, Any]) -> S2Request:
    o = _obj(raw, {"job_id", "company", "title", "s1", "s0", "catalog"}, "$")
    if isinstance(o["job_id"], bool) or not isinstance(o["job_id"], int): raise S2ParseError("job_id must be integer")
    try:
        s1raw = o["s1"]; quotes = [x.get("quote") for key in ("must_have", "nice_to_have", "responsibilities_summary") for x in s1raw.get(key, []) if isinstance(x, dict)] + [x for key in ("seniority_signals", "disqualifiers") for x in s1raw.get(key, []) if isinstance(x, str)]
        context = s1raw.get("company_context")
        if isinstance(context, dict): quotes.extend(item.get("quote") for item in context.values() if isinstance(item, dict) and isinstance(item.get("quote"), str))
        s1 = parse_s1_response_dict(s1raw, " ".join(quotes))
        catalog = parse_selection(o["catalog"])
        positioning = PositioningView(
            tuple(PositioningEntry(e.id, e.kind, e.label, e.label, e.keywords_exact, e.keywords_topical) for e in catalog.projects),
            tuple(PositioningEntry(e.id, e.kind, e.label, e.label, e.keywords_exact, e.keywords_topical) for e in catalog.experiences),
        )
        s0req = parse_s0_request({"job_id": o["job_id"], "company": o["company"], "title": o["title"], "context_mode": "jd_only", "s1": o["s1"], "positioning": {"projects": [{"id": e.id, "kind": e.kind, "label": e.label, "summary": e.label, "keywords_exact": list(e.keywords_exact), "keywords_topical": list(e.keywords_topical)} for e in catalog.projects], "experiences": [{"id": e.id, "kind": e.kind, "label": e.label, "summary": e.label, "keywords_exact": list(e.keywords_exact), "keywords_topical": list(e.keywords_topical)} for e in catalog.experiences]}})
        s0 = parse_s0_response(json.dumps(o["s0"], separators=(",", ":")), s0req)
    except S2ParseError: raise
    except Exception as exc: raise S2ParseError(f"invalid nested request: {exc}") from exc
    if s0req.job_id != o["job_id"]: raise S2SemanticError("nested job identity mismatch")
    return S2Request(o["job_id"], _str(o["company"], "company"), _str(o["title"], "title"), s1, s0, catalog)

def parse_s2_response(raw_output: str, request: S2Request) -> S2Response:
    try: value = json.loads(raw_output)
    except json.JSONDecodeError as exc: raise S2ParseError("invalid JSON") from exc
    o = _obj(value, {"base_variant", "projects", "bullet_order", "coverage"}, "$")
    choices = []
    if not isinstance(o["projects"], list): raise S2ParseError("projects must be array")
    for i, item in enumerate(o["projects"]):
        x = _obj(item, {"project_id", "reason", "s0_point_indexes"}, f"projects[{i}]")
        indexes = x["s0_point_indexes"]
        if not isinstance(indexes, list) or not indexes: raise S2ParseError("invalid S0 indexes")
        if any(isinstance(n, bool) or not isinstance(n, int) for n in indexes): raise S2ParseError("invalid S0 index type")
        choices.append(ProjectChoice(_str(x["project_id"], "project_id"), _str(x["reason"], "reason"), tuple(indexes)))
    order = _strs(o["bullet_order"], "bullet_order", True)
    coverage = []
    if not isinstance(o["coverage"], list): raise S2ParseError("coverage must be array")
    for i, item in enumerate(o["coverage"]):
        x = _obj(item, {"term", "status", "bullet_ids"}, f"coverage[{i}]")
        status = _str(x["status"], "coverage.status")
        if status not in {"covered", "gap"}: raise S2ParseError("invalid coverage status")
        ids = _strs(x["bullet_ids"], "coverage.bullet_ids")
        if status == "covered" and not ids: raise S2ParseError("covered entry needs bullets")
        if status == "gap" and ids: raise S2ParseError("gap must have no bullets")
        coverage.append(CoverageEntry(_str(x["term"], "coverage.term"), status, ids))
    response = S2Response(_str(o["base_variant"], "base_variant"), tuple(choices), order, tuple(coverage))
    validate_s2_selection(response, request)
    return response

def validate_s2_selection(response: S2Response, request: S2Request) -> None:
    catalog = request.catalog; variants = {v.name: v for v in catalog.variants}
    if response.base_variant not in variants: raise S2ValidationError("unknown base variant")
    base = variants[response.base_variant]; pids = {p.id for p in catalog.projects}; selected = [p.project_id for p in response.projects]
    if len(selected) != len(set(selected)): raise S2ValidationError("duplicate project")
    if any(p not in pids for p in selected): raise S2ValidationError("unknown project")
    if len(selected) != len(base.projects): raise S2ValidationError("wrong selected project count")
    removed = set(base.projects) - set(selected); added = set(selected) - set(base.projects)
    if len(removed) > 1 or len(added) > 1: raise S2ValidationError("more than one project swap")
    if any(i < 0 or i >= len(request.s0.points) for c in response.projects for i in c.s0_point_indexes): raise S2ValidationError("invalid S0 point reference")
    bullets = {b.id: b for b in catalog.bullets}
    if len(response.bullet_order) != len(base.bullet_order): raise S2ValidationError("wrong bullet count")
    if any(b not in bullets for b in response.bullet_order): raise S2ValidationError("unknown or blocked bullet")
    selected_set = set(response.bullet_order)
    for bid in selected_set:
        b = bullets[bid]
        if b.owner_kind == "project" and b.owner_id not in selected: raise S2ValidationError("bullet owned by unselected project")
    for project in selected:
        if not any(bullets[bid].owner_id == project for bid in selected_set): raise S2ValidationError("selected project has no selected bullet")
    observed_order: list[str] = []
    observed_counts: list[tuple[str, int]] = []
    closed_experiences: set[str] = set()
    active_owner: str | None = None
    for bullet_id in response.bullet_order:
        bullet = bullets[bullet_id]
        if bullet.owner_kind != "experience":
            continue
        owner = bullet.owner_id
        if owner != active_owner:
            if owner in closed_experiences:
                raise S2ValidationError("experience owner appears in disjoint groups")
            if active_owner is not None:
                closed_experiences.add(active_owner)
            active_owner = owner
            observed_order.append(owner)
            observed_counts.append((owner, 0))
        observed_counts[-1] = (owner, observed_counts[-1][1] + 1)
    if tuple(observed_order) != base.experience_order or tuple(observed_counts) != base.experience_bullet_counts:
        raise S2ValidationError("experience ordering or counts changed")
    last: dict[str, int] = {}
    for bid in response.bullet_order:
        b = bullets[bid]
        if b.owner_id in last and b.priority < last[b.owner_id]: raise S2ValidationError("decreasing priority within owner")
        last[b.owner_id] = b.priority
    required = [x.term for x in request.s1.must_have]
    terms = [x.term for x in response.coverage]
    if len(terms) != len(set(terms)) or terms != required: raise S2ValidationError("coverage must contain each must_have exactly once and in order")
    blocked = {_norm(x) for x in catalog.do_not_claim}; covered = set(response.bullet_order)
    for entry in response.coverage:
        if _norm(entry.term) in blocked and entry.status == "covered": raise S2ValidationError("do_not_claim term covered")
        if entry.status == "covered":
            if any(bid not in covered for bid in entry.bullet_ids): raise S2ValidationError("coverage cites unselected bullet")
            if not any(_norm(entry.term) == _norm(keyword) for bid in entry.bullet_ids for keyword in bullets[bid].keywords_hit): raise S2ValidationError("covered term has no exact keyword hit")

def s2_response_to_dict(response: S2Response) -> dict[str, Any]:
    return {"base_variant": response.base_variant, "projects": [{"project_id": p.project_id, "reason": p.reason, "s0_point_indexes": list(p.s0_point_indexes)} for p in response.projects], "bullet_order": list(response.bullet_order), "coverage": [{"term": c.term, "status": c.status, "bullet_ids": list(c.bullet_ids)} for c in response.coverage]}

S2_REQUEST_MARKER = "{{S2_REQUEST_JSON}}"
def build_s2_prompt(template_text: str, request: S2Request) -> str:
    if template_text.count(S2_REQUEST_MARKER) != 1: raise ValueError(f"S2 prompt template must contain {S2_REQUEST_MARKER!r} exactly once")
    return template_text.replace(S2_REQUEST_MARKER, json.dumps(s2_request_to_dict(request), indent=2, sort_keys=True))
