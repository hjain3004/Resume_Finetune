"""S1 requirement-extraction contract (M8P-1).

Typed, frozen dataclasses at the module boundary plus a strict, pure JSON
parser with JD-anchored semantic validation. No filesystem I/O, no network,
no model calls anywhere in this module -- see docs/superpowers/specs/
2026-08-21-m8-human-pilot-s1-design.md for the approved design this
implements.

Two distinct failure classes, kept separate so callers (the orchestrator)
can report "parse/schema failure" and "semantic-validation failure" as
different outcomes:

- S1ParseError: strict-JSON / structural contract violations (malformed
  JSON, missing/unexpected fields, wrong types, empty strings, duplicate
  requirements/quotes). Detectable without the JD.
- S1SemanticError: the response is structurally valid but fails JD
  anchoring (a quote is not an exact JD substring, a term is not an exact
  substring of its own quote).
"""

from __future__ import annotations

import json
from dataclasses import dataclass

#: Bound applied to any untrusted text (raw model output, JD excerpts)
#: embedded in an error message, so a diagnostic can never balloon to the
#: size of the offending payload.
_DIAGNOSTIC_MAX_CHARS = 200

S1_REQUEST_MARKER = "{{S1_REQUEST_JSON}}"


class S1ParseError(ValueError):
    """Strict-JSON / structural contract violation."""


class S1SemanticError(ValueError):
    """Structurally valid response that fails JD-anchored validation."""


@dataclass(frozen=True)
class Requirement:
    term: str
    quote: str


@dataclass(frozen=True)
class AnchoredSummary:
    summary: str
    quote: str


@dataclass(frozen=True)
class AnchoredClaim:
    claim: str
    quote: str


@dataclass(frozen=True)
class CompanyContext:
    domain: AnchoredClaim | None
    product: AnchoredClaim | None
    stage_or_scale: AnchoredClaim | None


@dataclass(frozen=True)
class InjectionFlag:
    quote: str
    reason: str


@dataclass(frozen=True)
class S1Request:
    job_id: int
    company: str
    title: str
    jd_text: str
    jd_quality: str


@dataclass(frozen=True)
class S1Response:
    must_have: tuple[Requirement, ...]
    nice_to_have: tuple[Requirement, ...]
    responsibilities_summary: tuple[AnchoredSummary, ...]
    seniority_signals: tuple[str, ...]
    disqualifiers: tuple[str, ...]
    company_context: CompanyContext | None
    suspected_injection: tuple[InjectionFlag, ...]

    @property
    def is_injection_suspected(self) -> bool:
        return len(self.suspected_injection) > 0


# ---------------------------------------------------------------------------
# Small structural helpers (shared by response and request parsing)
# ---------------------------------------------------------------------------


def _bounded(text: str, limit: int = _DIAGNOSTIC_MAX_CHARS) -> str:
    text = text if isinstance(text, str) else repr(text)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}...<truncated {len(text) - limit} chars>"


def _normalize(value: str) -> str:
    return " ".join(value.casefold().split())


def _require_dict(value: object, path: str) -> dict:
    if not isinstance(value, dict):
        raise S1ParseError(f"{path}: expected object, got {type(value).__name__}")
    return value


def _require_list(value: object, path: str) -> list:
    if not isinstance(value, list):
        raise S1ParseError(f"{path}: expected array, got {type(value).__name__}")
    return value


def _require_str(value: object, path: str) -> str:
    if not isinstance(value, str):
        raise S1ParseError(f"{path}: expected string, got {type(value).__name__}")
    if not value.strip():
        raise S1ParseError(f"{path}: expected nonempty string")
    return value


def _require_fields(raw: dict, required: set[str], path: str) -> None:
    missing = required - set(raw)
    if missing:
        raise S1ParseError(f"{path}: missing required field(s): {', '.join(sorted(missing))}")


def _reject_unexpected(raw: dict, allowed: set[str], path: str) -> None:
    extra = set(raw) - allowed
    if extra:
        raise S1ParseError(f"{path}: unexpected field(s): {', '.join(sorted(extra))}")


def _require_object(raw: object, keys: set[str], path: str) -> dict:
    obj = _require_dict(raw, path)
    _require_fields(obj, keys, path)
    _reject_unexpected(obj, keys, path)
    return obj


# ---------------------------------------------------------------------------
# Sub-object parsers
# ---------------------------------------------------------------------------

_REQUIREMENT_KEYS = {"term", "quote"}
_SUMMARY_KEYS = {"summary", "quote"}
_CLAIM_KEYS = {"claim", "quote"}
_CONTEXT_KEYS = {"domain", "product", "stage_or_scale"}
_INJECTION_KEYS = {"quote", "reason"}


def _parse_requirement(raw: object, path: str) -> Requirement:
    obj = _require_object(raw, _REQUIREMENT_KEYS, path)
    return Requirement(
        term=_require_str(obj["term"], f"{path}.term"),
        quote=_require_str(obj["quote"], f"{path}.quote"),
    )


def _parse_requirement_list(raw: object, path: str) -> tuple[Requirement, ...]:
    items = _require_list(raw, path)
    return tuple(_parse_requirement(item, f"{path}[{i}]") for i, item in enumerate(items))


def _check_no_duplicate_terms(
    must_have: tuple[Requirement, ...], nice_to_have: tuple[Requirement, ...]
) -> None:
    seen: dict[str, str] = {}
    for label, items in (("must_have", must_have), ("nice_to_have", nice_to_have)):
        for i, req in enumerate(items):
            norm = _normalize(req.term)
            entry_path = f"{label}[{i}].term"
            if norm in seen:
                raise S1ParseError(
                    f"{entry_path}: duplicate requirement term (normalized) already used "
                    f"at {seen[norm]}: {req.term!r}"
                )
            seen[norm] = entry_path


def _parse_summary(raw: object, path: str) -> AnchoredSummary:
    obj = _require_object(raw, _SUMMARY_KEYS, path)
    return AnchoredSummary(
        summary=_require_str(obj["summary"], f"{path}.summary"),
        quote=_require_str(obj["quote"], f"{path}.quote"),
    )


def _parse_summary_list(raw: object, path: str) -> tuple[AnchoredSummary, ...]:
    items = _require_list(raw, path)
    return tuple(_parse_summary(item, f"{path}[{i}]") for i, item in enumerate(items))


def _parse_quote_list(raw: object, path: str) -> tuple[str, ...]:
    items = _require_list(raw, path)
    result: list[str] = []
    seen: set[str] = set()
    for i, item in enumerate(items):
        quote = _require_str(item, f"{path}[{i}]")
        if quote in seen:
            raise S1ParseError(f"{path}[{i}]: duplicate quote already present in this list: {_bounded(quote)!r}")
        seen.add(quote)
        result.append(quote)
    return tuple(result)


def _parse_claim(raw: object, path: str) -> AnchoredClaim:
    obj = _require_object(raw, _CLAIM_KEYS, path)
    return AnchoredClaim(
        claim=_require_str(obj["claim"], f"{path}.claim"),
        quote=_require_str(obj["quote"], f"{path}.quote"),
    )


def _parse_nullable_claim(raw: object, path: str) -> AnchoredClaim | None:
    if raw is None:
        return None
    return _parse_claim(raw, path)


def _parse_company_context(raw: object, path: str) -> CompanyContext | None:
    if raw is None:
        return None
    obj = _require_object(raw, _CONTEXT_KEYS, path)
    domain = _parse_nullable_claim(obj["domain"], f"{path}.domain")
    product = _parse_nullable_claim(obj["product"], f"{path}.product")
    stage_or_scale = _parse_nullable_claim(obj["stage_or_scale"], f"{path}.stage_or_scale")
    if domain is None and product is None and stage_or_scale is None:
        return None
    return CompanyContext(domain=domain, product=product, stage_or_scale=stage_or_scale)


def _parse_injection_flag(raw: object, path: str) -> InjectionFlag:
    obj = _require_object(raw, _INJECTION_KEYS, path)
    return InjectionFlag(
        quote=_require_str(obj["quote"], f"{path}.quote"),
        reason=_require_str(obj["reason"], f"{path}.reason"),
    )


def _parse_injection_list(raw: object, path: str) -> tuple[InjectionFlag, ...]:
    items = _require_list(raw, path)
    return tuple(_parse_injection_flag(item, f"{path}[{i}]") for i, item in enumerate(items))


# ---------------------------------------------------------------------------
# Semantic (JD-anchored) validation
# ---------------------------------------------------------------------------


def _check_substring(quote: str, jd_text: str, path: str) -> None:
    if quote not in jd_text:
        raise S1SemanticError(f"{path}: quote is not an exact substring of the JD: {_bounded(quote)!r}")


def _validate_semantics(response: S1Response, jd_text: str) -> None:
    for i, req in enumerate(response.must_have):
        _check_substring(req.quote, jd_text, f"$.must_have[{i}].quote")
        if req.term not in req.quote:
            raise S1SemanticError(
                f"$.must_have[{i}].term: term is not an exact substring of its own quote: {_bounded(req.term)!r}"
            )
    for i, req in enumerate(response.nice_to_have):
        _check_substring(req.quote, jd_text, f"$.nice_to_have[{i}].quote")
        if req.term not in req.quote:
            raise S1SemanticError(
                f"$.nice_to_have[{i}].term: term is not an exact substring of its own quote: {_bounded(req.term)!r}"
            )
    for i, item in enumerate(response.responsibilities_summary):
        _check_substring(item.quote, jd_text, f"$.responsibilities_summary[{i}].quote")
    for i, quote in enumerate(response.seniority_signals):
        _check_substring(quote, jd_text, f"$.seniority_signals[{i}]")
    for i, quote in enumerate(response.disqualifiers):
        _check_substring(quote, jd_text, f"$.disqualifiers[{i}]")
    if response.company_context is not None:
        for field_name in ("domain", "product", "stage_or_scale"):
            claim = getattr(response.company_context, field_name)
            if claim is not None:
                _check_substring(claim.quote, jd_text, f"$.company_context.{field_name}.quote")
    for i, flag in enumerate(response.suspected_injection):
        _check_substring(flag.quote, jd_text, f"$.suspected_injection[{i}].quote")


# ---------------------------------------------------------------------------
# Public parser
# ---------------------------------------------------------------------------

_TOP_LEVEL_KEYS = {
    "must_have",
    "nice_to_have",
    "responsibilities_summary",
    "seniority_signals",
    "disqualifiers",
    "company_context",
    "suspected_injection",
}


def parse_s1_response(raw_output: str, jd_text: str) -> S1Response:
    """Strictly parse and JD-anchor-validate a raw S1 model response.

    Pure: no filesystem I/O. Raises S1ParseError for any structural
    violation (malformed JSON, markdown fences, trailing commas, missing/
    unexpected/wrong-typed fields, empty strings, duplicate requirements
    or quotes) and S1SemanticError once the shape is valid but a quote or
    term fails to anchor to `jd_text` exactly.
    """
    try:
        parsed = json.loads(raw_output)
    except json.JSONDecodeError as exc:
        raise S1ParseError(f"$: invalid JSON ({exc}); raw output (bounded): {_bounded(raw_output)!r}") from exc

    obj = _require_object(parsed, _TOP_LEVEL_KEYS, "$")

    must_have = _parse_requirement_list(obj["must_have"], "$.must_have")
    nice_to_have = _parse_requirement_list(obj["nice_to_have"], "$.nice_to_have")
    _check_no_duplicate_terms(must_have, nice_to_have)

    responsibilities_summary = _parse_summary_list(
        obj["responsibilities_summary"], "$.responsibilities_summary"
    )
    seniority_signals = _parse_quote_list(obj["seniority_signals"], "$.seniority_signals")
    disqualifiers = _parse_quote_list(obj["disqualifiers"], "$.disqualifiers")
    company_context = _parse_company_context(obj["company_context"], "$.company_context")
    suspected_injection = _parse_injection_list(obj["suspected_injection"], "$.suspected_injection")

    response = S1Response(
        must_have=must_have,
        nice_to_have=nice_to_have,
        responsibilities_summary=responsibilities_summary,
        seniority_signals=seniority_signals,
        disqualifiers=disqualifiers,
        company_context=company_context,
        suspected_injection=suspected_injection,
    )

    _validate_semantics(response, jd_text)
    return response


# ---------------------------------------------------------------------------
# S1Request (de)serialization + prompt building
# ---------------------------------------------------------------------------

_REQUEST_KEYS = {"job_id", "company", "title", "jd_text", "jd_quality"}


def s1_request_to_dict(request: S1Request) -> dict:
    return {
        "job_id": request.job_id,
        "company": request.company,
        "title": request.title,
        "jd_text": request.jd_text,
        "jd_quality": request.jd_quality,
    }


def parse_s1_request(raw: dict) -> S1Request:
    """Strictly parse a persisted `s1_request.json` payload. Pure."""
    obj = _require_object(raw, _REQUEST_KEYS, "$")
    job_id = obj["job_id"]
    if isinstance(job_id, bool) or not isinstance(job_id, int):
        raise S1ParseError(f"$.job_id: expected integer, got {type(job_id).__name__}")
    return S1Request(
        job_id=job_id,
        company=_require_str(obj["company"], "$.company"),
        title=_require_str(obj["title"], "$.title"),
        jd_text=_require_str(obj["jd_text"], "$.jd_text"),
        jd_quality=_require_str(obj["jd_quality"], "$.jd_quality"),
    )


def s1_response_to_dict(response: S1Response) -> dict:
    """Serialize a validated S1Response for atomic publication as s1.json."""

    def _requirement(item: Requirement) -> dict:
        return {"term": item.term, "quote": item.quote}

    def _summary(item: AnchoredSummary) -> dict:
        return {"summary": item.summary, "quote": item.quote}

    def _claim(item: AnchoredClaim | None) -> dict | None:
        return None if item is None else {"claim": item.claim, "quote": item.quote}

    def _injection(item: InjectionFlag) -> dict:
        return {"quote": item.quote, "reason": item.reason}

    company_context = None
    if response.company_context is not None:
        company_context = {
            "domain": _claim(response.company_context.domain),
            "product": _claim(response.company_context.product),
            "stage_or_scale": _claim(response.company_context.stage_or_scale),
        }

    return {
        "must_have": [_requirement(item) for item in response.must_have],
        "nice_to_have": [_requirement(item) for item in response.nice_to_have],
        "responsibilities_summary": [_summary(item) for item in response.responsibilities_summary],
        "seniority_signals": list(response.seniority_signals),
        "disqualifiers": list(response.disqualifiers),
        "company_context": company_context,
        "suspected_injection": [_injection(item) for item in response.suspected_injection],
    }


def build_s1_prompt(template_text: str, request: S1Request) -> str:
    """Embed the S1 request (including the untrusted JD text) into the
    protected S1 prompt template at its `{{S1_REQUEST_JSON}}` marker."""
    if S1_REQUEST_MARKER not in template_text:
        raise ValueError(f"S1 prompt template is missing the {S1_REQUEST_MARKER!r} marker")
    request_json = json.dumps(s1_request_to_dict(request), indent=2)
    return template_text.replace(S1_REQUEST_MARKER, request_json)
