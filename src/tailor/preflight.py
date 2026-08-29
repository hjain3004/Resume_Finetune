"""Model-free tailoring preflight (M8V-1). Every check here is deterministic
and catches a class of defect that does not need a model call to detect:
a do_not_claim term leaking onto a rendered surface, a broken prompt
invariant (a markdown fence, a duplicated or missing substitution marker,
a documented response shape its own parser structurally rejects), or a
base variant that fails to render to one page or fails L7. No model call,
no network, no SQLite write -- this module makes no live invocation and
does not import the invocation or trace-logging modules."""
from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from src.profile import BaseVariant, MasterProfile
from src.tailor.lint import contains_normalized_phrase

#: Every rendered surface a do_not_claim term could leak onto. `tech_line`
#: and `display_title` are the two that escaped L6 (which only inspects
#: bullet plain text and the skills mapping) -- failure #3.
SURFACES = ("bullet_phrasings", "skills", "tech_line", "display_title", "project_name")

_FENCE_PREFIX = "```"


@dataclass(frozen=True)
class PreflightFinding:
    check: str  # "profile_do_not_claim" | "render_l7" | "prompt_invariants"
    surface: str
    message: str


@dataclass(frozen=True)
class PreflightReport:
    findings: tuple[PreflightFinding, ...]
    passed: bool


# ---------------------------------------------------------------------------
# check_profile_do_not_claim
# ---------------------------------------------------------------------------


def check_profile_do_not_claim(profile: MasterProfile) -> tuple[PreflightFinding, ...]:
    """Scan every rendered surface, not just the two G1's L6 inspects."""
    if not profile.do_not_claim:
        return ()

    findings: list[PreflightFinding] = []

    def _scan(text: str, surface: str, location: str) -> None:
        for term in profile.do_not_claim:
            if contains_normalized_phrase(text, term):
                findings.append(PreflightFinding(
                    check="profile_do_not_claim", surface=surface,
                    message=f"{location}: do_not_claim term {term!r} found in {surface}",
                ))

    for project in profile.projects:
        _scan(project.display_title, "display_title", project.id)
        _scan(project.tech_line, "tech_line", project.id)
        _scan(project.name, "project_name", project.id)

    for source in (*profile.projects, *profile.experience):
        for bullet in source.bullets:
            for phrasing in (bullet.phrasings.short, bullet.phrasings.medium, bullet.phrasings.long):
                if phrasing:
                    _scan(phrasing, "bullet_phrasings", bullet.id)

    for category, terms in profile.skills.items():
        for term in terms:
            _scan(term, "skills", category)

    return tuple(findings)


# ---------------------------------------------------------------------------
# check_prompt_invariants
# ---------------------------------------------------------------------------


def _expected_marker(prompt_path: Path) -> str:
    """`tailoring_s1.md` -> `S1_REQUEST_JSON`, matching every prompt's own
    naming convention (`{{<STAGE>_REQUEST_JSON}}`)."""
    stem = prompt_path.stem
    suffix = stem.split("_", 1)[1] if "_" in stem else stem
    return f"{suffix.upper()}_REQUEST_JSON"


def _extract_json_objects(text: str) -> list[str]:
    """Every maximal balanced-brace substring at top level (depth 0->1).
    The `{{MARKER}}` substitution syntax is naturally skipped: its content
    has no internal braces, so `json.loads` on the captured `{MARKER}`-style
    substring simply fails to parse and the caller discards it."""
    blocks: list[str] = []
    depth = 0
    start: int | None = None
    for index, char in enumerate(text):
        if char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    blocks.append(text[start:index + 1])
                    start = None
    return blocks


class _SyntheticShapeContext:
    """A fully synthetic, profile-independent context sufficient to run
    each stage's own structural parser against its documented example.
    Every collection is deliberately empty so the degenerate selection is
    self-consistent by construction (zero must-haves means zero coverage
    obligations, zero selected projects means zero required bullets, and
    so on) -- this proves nothing about real tailoring, only that the
    documented JSON shape itself is well-formed."""

    def __init__(self) -> None:
        from src.tailor.alignment_view import alignment_from_profile
        from src.tailor.g2 import G2Request
        from src.tailor.profile_views import PositioningView, SelectionCatalog, SelectionVariant
        from src.tailor.s0 import S0Response, build_s0_request
        from src.tailor.s1 import S1Response
        from src.tailor.s2 import S2Response, build_s2_request
        from src.tailor.s3 import build_s3_request

        s1 = S1Response(
            must_have=(), nice_to_have=(), responsibilities_summary=(),
            seniority_signals=(), disqualifiers=(), company_context=None,
            suspected_injection=(),
        )
        positioning = PositioningView(projects=(), experiences=())
        self.s0_request = build_s0_request(1, "Synthetic", "Engineer", s1, positioning)
        s0 = S0Response(context_mode="jd_only", points=())

        catalog = SelectionCatalog(
            recommended_base_variant="synthetic",
            variants=(SelectionVariant(
                name="synthetic", projects=(), bullet_order=(),
                experience_order=(), experience_bullet_counts=(),
            ),),
            projects=(), experiences=(), bullets=(), do_not_claim=(),
        )
        self.s2_request = build_s2_request(1, "Synthetic", "Engineer", s1, s0, catalog)
        s2 = S2Response(base_variant="synthetic", projects=(), bullet_order=(), coverage=())

        synthetic_profile = MasterProfile(
            schema_version="synthetic", last_updated="2026-01-01", ats={},
            identity={}, education=(), skills={}, projects=(), experience=(),
            base_variants={"synthetic": BaseVariant(projects=(), bullet_order=())},
            do_not_claim=(),
        )
        alignment = alignment_from_profile(synthetic_profile, self.s2_request, s2)
        self.s3_request = build_s3_request(1, "Synthetic", "Engineer", s1, s0, s2, alignment)

        self.g2_request = G2Request(
            job_id=1, company="Synthetic", title="Engineer", context_mode="jd_only",
            round_index=1, positioning=s0, must_have=(), nice_to_have=(), coverage=(),
            changed_bullets=(), skill_additions=(), unchanged_bullets=(),
            unified_diff="", banned_terms=(), taste_lessons=(), prior_findings=(),
            alignment_fingerprint="", bundle_schema_version="synthetic",
        )


def _shape_passes(blocks: list[str], parse_fn, parse_error_cls) -> bool:
    """True if at least one candidate JSON block in the prompt parses
    through the stage's own parser without raising its ParseError -- a
    SemanticError (or any other exception) is tolerated, since a
    documented example uses illustrative placeholder content that cannot
    satisfy content-level semantic rules (a quote being a real JD
    substring, a term citing a real profile id) by construction. Only a
    *structural* rejection -- a missing field, a wrong type, invalid JSON --
    is a genuine shape defect."""
    if not blocks:
        return True
    for block in blocks:
        try:
            parse_fn(block)
        except parse_error_cls:
            continue
        except Exception:
            return True
        else:
            return True
    return False


def _check_documented_shape(stage: str, blocks: list[str]) -> tuple[str, ...]:
    """Returns bare message strings (the caller prefixes them with the
    prompt filename); empty when the shape is fine or the stage is unknown."""
    if not blocks:
        return ()
    try:
        ctx = _SyntheticShapeContext()
    except Exception:
        # The synthetic context itself failed to build -- a preflight bug,
        # not a prompt defect. Do not report a false shape finding.
        return ()

    if stage == "s1":
        from src.tailor.s1 import S1ParseError, parse_s1_response
        ok = _shape_passes(blocks, lambda raw: parse_s1_response(raw, ""), S1ParseError)
    elif stage == "s0":
        from src.tailor.s0 import S0ParseError, parse_s0_response
        ok = _shape_passes(blocks, lambda raw: parse_s0_response(raw, ctx.s0_request), S0ParseError)
    elif stage == "s2":
        from src.tailor.s2 import S2ParseError, parse_s2_response
        ok = _shape_passes(blocks, lambda raw: parse_s2_response(raw, ctx.s2_request), S2ParseError)
    elif stage == "s3":
        from src.tailor.s3 import S3ParseError, parse_s3_response
        ok = _shape_passes(blocks, lambda raw: parse_s3_response(raw, ctx.s3_request), S3ParseError)
    elif stage == "g2":
        from src.tailor.g2 import G2ParseError, parse_g2_response
        ok = _shape_passes(blocks, lambda raw: parse_g2_response(raw, ctx.g2_request), G2ParseError)
    else:
        return ()

    if ok:
        return ()
    return ("documented response shape is rejected by its own parser (structural)",)


def check_prompt_invariants(prompt_dir: Path) -> tuple[PreflightFinding, ...]:
    findings: list[PreflightFinding] = []
    for prompt_path in sorted(Path(prompt_dir).glob("*.md")):
        text = prompt_path.read_text(encoding="utf-8")
        name = prompt_path.name

        for line_no, line in enumerate(text.splitlines(), start=1):
            if line.strip().startswith(_FENCE_PREFIX):
                findings.append(PreflightFinding(
                    check="prompt_invariants", surface=name,
                    message=f"{name}:{line_no}: markdown fence forbidden by this prompt's own rules",
                ))

        marker = _expected_marker(prompt_path)
        marker_text = "{{" + marker + "}}"
        count = text.count(marker_text)
        if count != 1:
            findings.append(PreflightFinding(
                check="prompt_invariants", surface=name,
                message=f"{name}: substitution marker {marker_text!r} must appear exactly once, found {count}",
            ))

        stage = marker.split("_", 1)[0].lower()
        blocks = _extract_json_objects(text)
        for message in _check_documented_shape(stage, blocks):
            findings.append(PreflightFinding(
                check="prompt_invariants", surface=name, message=f"{name}: {message}",
            ))

    return tuple(findings)


# ---------------------------------------------------------------------------
# check_variants_render
# ---------------------------------------------------------------------------


def check_variants_render(profile: MasterProfile, template: Path, workdir: Path) -> tuple[PreflightFinding, ...]:
    """One pdflatex run per base variant, canonical (untailored) content
    only -- catches a variant that overflows to a second page or fails L7
    before any model call ever produces a draft to tailor."""
    from src.render.l7 import run_l7
    from src.render.latex import render_latex
    from src.render.parse import parse_pdf
    from src.render.tailored import render_doc_from_draft
    from src.tailor.alignment_view import alignment_from_profile
    from src.tailor.s0 import S0Response, build_s0_request
    from src.tailor.s1 import S1Response
    from src.tailor.s2 import ProjectChoice, S2Response, build_s2_request
    from src.tailor.s3 import S3Response, build_s3_request, hydrate_s3

    if shutil.which("pdflatex") is None:
        return ()

    findings: list[PreflightFinding] = []
    s1 = S1Response(
        must_have=(), nice_to_have=(), responsibilities_summary=(),
        seniority_signals=(), disqualifiers=(), company_context=None,
        suspected_injection=(),
    )
    positioning = profile.for_positioning()

    for variant_name in profile.base_variants:
        catalog = profile.for_selection(variant_name)
        variant = next(v for v in catalog.variants if v.name == variant_name)
        build_s0_request(1, "Preflight", "Engineer", s1, positioning)  # validates positioning shape
        s0 = S0Response(context_mode="jd_only", points=())
        s2_request = build_s2_request(1, "Preflight", "Engineer", s1, s0, catalog)
        s2 = S2Response(
            base_variant=variant_name,
            projects=tuple(ProjectChoice(project_id=pid, reason="canonical", s0_point_indexes=()) for pid in variant.projects),
            bullet_order=variant.bullet_order, coverage=(),
        )
        alignment = alignment_from_profile(profile, s2_request, s2)
        s3_request = build_s3_request(1, "Preflight", "Engineer", s1, s0, s2, alignment)
        draft = hydrate_s3(s3_request, S3Response(bullet_edits=(), skill_additions=()))

        doc = render_doc_from_draft(profile, draft)
        with tempfile.TemporaryDirectory(dir=workdir) as tmp:
            tmp_pdf = Path(tmp) / "resume.pdf"
            try:
                render_latex(doc, template, tmp_pdf)
                parsed = parse_pdf(tmp_pdf)
            except Exception as exc:
                findings.append(PreflightFinding(
                    check="render_l7", surface=variant_name,
                    message=f"{variant_name}: render failed: {exc}",
                ))
                continue
            if parsed.page_count != 1:
                findings.append(PreflightFinding(
                    check="render_l7", surface=variant_name,
                    message=f"{variant_name}: renders to {parsed.page_count} page(s), expected 1",
                ))
            for violation in run_l7(doc, parsed):
                findings.append(PreflightFinding(
                    check="render_l7", surface=variant_name, message=f"{variant_name}: {violation}",
                ))
    return tuple(findings)


# ---------------------------------------------------------------------------
# run_preflight
# ---------------------------------------------------------------------------


def run_preflight(
    profile_path: Path, template: Path, prompt_dir: Path, workdir: Path, *, skip_render: bool = False,
) -> PreflightReport:
    from src.profile import load_profile

    profile = load_profile(profile_path)
    findings: list[PreflightFinding] = []
    findings.extend(check_profile_do_not_claim(profile))
    findings.extend(check_prompt_invariants(prompt_dir))
    if not skip_render:
        findings.extend(check_variants_render(profile, template, workdir))
    findings_tuple = tuple(findings)
    return PreflightReport(findings=findings_tuple, passed=not findings_tuple)
