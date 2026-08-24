"""Strict, JD-only S0 positioning contract."""
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any

from src.tailor.profile_views import PositioningView, positioning_to_dict, parse_positioning
from src.tailor.s1 import S1Request, S1Response, S1SemanticError, s1_request_to_dict, s1_response_to_dict, parse_s1_request, parse_s1_response_dict

_MAX = 200
S0_REQUEST_MARKER = "{{S0_REQUEST_JSON}}"


class S0ParseError(ValueError): pass
class S0SemanticError(ValueError): pass
class ContextMode(str, Enum): JD_ONLY = "jd_only"


@dataclass(frozen=True)
class PositioningPoint:
    sentence: str
    profile_ids: tuple[str, ...]
    requirement_terms: tuple[str, ...]
    jd_quotes: tuple[str, ...]


@dataclass(frozen=True)
class S0Request:
    job_id: int
    company: str
    title: str
    s1: S1Response
    positioning: PositioningView
    context_mode: str = ContextMode.JD_ONLY.value


@dataclass(frozen=True)
class S0Response:
    context_mode: str
    points: tuple[PositioningPoint, ...]


def _bounded(value: object) -> str:
    text = repr(value)
    return text if len(text) <= _MAX else text[:_MAX] + "..."


def _normalize(value: str) -> str:
    return " ".join(value.casefold().split())


def _str(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip(): raise S0ParseError(f"{path}: expected nonempty string")
    return value


def _list(value: object, path: str) -> list:
    if not isinstance(value, list) or not value: raise S0ParseError(f"{path}: expected nonempty array")
    return value


def _object(value: object, fields: set[str], path: str) -> dict:
    if not isinstance(value, dict): raise S0ParseError(f"{path}: expected object")
    if set(value) != fields: raise S0ParseError(f"{path}: unexpected or missing fields")
    return value


def build_s0_request(job_id: int, company: str, title: str, s1: S1Response, positioning: PositioningView) -> S0Request:
    return S0Request(job_id, company, title, s1, positioning)


def s0_request_to_dict(request: S0Request) -> dict[str, Any]:
    return {"job_id": request.job_id, "company": request.company, "title": request.title, "context_mode": request.context_mode, "s1": s1_response_to_dict(request.s1), "positioning": positioning_to_dict(request.positioning)}


def parse_s0_request(raw: dict[str, Any]) -> S0Request:
    o = _object(raw, {"job_id", "company", "title", "context_mode", "s1", "positioning"}, "$")
    if isinstance(o["job_id"], bool) or not isinstance(o["job_id"], int): raise S0ParseError("$.job_id: expected integer")
    if o["context_mode"] != ContextMode.JD_ONLY.value: raise S0SemanticError("context_mode must be jd_only")
    try:
        # JD anchoring is performed when the S1 request is available; request artifacts contain no raw JD.
        serialized = o["s1"]
        jd_parts = []
        for key in ("must_have", "nice_to_have", "responsibilities_summary"):
            jd_parts.extend(item["quote"] for item in serialized.get(key, []) if isinstance(item, dict) and isinstance(item.get("quote"), str))
        jd_parts.extend(item for key in ("seniority_signals", "disqualifiers") for item in serialized.get(key, []) if isinstance(item, str))
        context = serialized.get("company_context")
        if isinstance(context, dict):
            jd_parts.extend(item.get("quote") for item in context.values() if isinstance(item, dict) and isinstance(item.get("quote"), str))
        s1 = parse_s1_response_dict(serialized, " ".join(jd_parts))
    except Exception as exc:
        # Persisted S0 request is structurally parsed here; preparation revalidates S1 against the JD.
        if isinstance(exc, S0ParseError): raise
        raise S0ParseError(f"$.s1: invalid persisted response: {exc}") from exc
    try: positioning = parse_positioning(o["positioning"])
    except Exception as exc: raise S0ParseError(f"$.positioning: {exc}") from exc
    return S0Request(o["job_id"], _str(o["company"], "$.company"), _str(o["title"], "$.title"), s1, positioning)


def _pool(s1: S1Response) -> tuple[str, ...]:
    values = [*(r.quote for r in s1.must_have), *(r.quote for r in s1.nice_to_have), *(x.quote for x in s1.responsibilities_summary), *s1.seniority_signals, *s1.disqualifiers]
    if s1.company_context:
        values.extend(x.quote for x in (s1.company_context.domain, s1.company_context.product, s1.company_context.stage_or_scale) if x)
    return tuple(dict.fromkeys(values))


def parse_s0_response(raw_output: str, request: S0Request) -> S0Response:
    try: value = json.loads(raw_output)
    except json.JSONDecodeError as exc: raise S0ParseError(f"$: invalid JSON: {_bounded(exc)}") from exc
    o = _object(value, {"context_mode", "points"}, "$")
    if o["context_mode"] != "jd_only": raise S0SemanticError("context_mode must be jd_only")
    raw_points = _list(o["points"], "$.points")
    if len(raw_points) < 2 or len(raw_points) > 4: raise S0ParseError("$.points: expected two to four points")
    ids = {x.id for x in (*request.positioning.projects, *request.positioning.experiences)}
    terms = {_term.term for _term in (*request.s1.must_have, *request.s1.nice_to_have)}
    quotes = set(_pool(request.s1)); points = []
    sentences = set()
    for i, raw in enumerate(raw_points):
        p = _object(raw, {"sentence", "profile_ids", "requirement_terms", "jd_quotes"}, f"$.points[{i}]")
        sentence = _str(p["sentence"], "sentence"); key = " ".join(sentence.casefold().split())
        if key in sentences: raise S0ParseError("duplicate normalized sentence")
        sentences.add(key)
        profile_ids = tuple(_str(x, "profile_id") for x in _list(p["profile_ids"], "profile_ids")); req_terms = tuple(_str(x, "term") for x in _list(p["requirement_terms"], "requirement_terms")); jd_quotes = tuple(_str(x, "quote") for x in _list(p["jd_quotes"], "jd_quotes"))
        if len({_normalize(value) for value in profile_ids}) != len(profile_ids) or len({_normalize(value) for value in req_terms}) != len(req_terms) or len({_normalize(value) for value in jd_quotes}) != len(jd_quotes): raise S0ParseError("duplicate point citation")
        if any(x not in ids for x in profile_ids): raise S0SemanticError("unknown profile id")
        if any(x not in terms for x in req_terms): raise S0SemanticError("requirement term is not in S1")
        if any(x not in quotes for x in jd_quotes): raise S0SemanticError("quote is not in S1 evidence pool")
        points.append(PositioningPoint(sentence, profile_ids, req_terms, jd_quotes))
    return S0Response("jd_only", tuple(points))


def s0_response_to_dict(response: S0Response) -> dict[str, Any]:
    return {"context_mode": response.context_mode, "points": [{"sentence": p.sentence, "profile_ids": list(p.profile_ids), "requirement_terms": list(p.requirement_terms), "jd_quotes": list(p.jd_quotes)} for p in response.points]}


def build_s0_prompt(template_text: str, request: S0Request) -> str:
    if template_text.count(S0_REQUEST_MARKER) != 1: raise ValueError(f"S0 prompt template must contain {S0_REQUEST_MARKER!r} exactly once")
    return template_text.replace(S0_REQUEST_MARKER, json.dumps(s0_request_to_dict(request), indent=2, sort_keys=True))
