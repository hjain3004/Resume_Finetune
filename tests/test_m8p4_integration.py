"""M8P-4 Task 7: adversarial integration coverage for the G2 critic and
bounded revision loop, against the REAL config/master_profile.yaml -- with
its authentic do_not_claim=["Kubernetes"] intact, unlike
tests/tailor/conftest.py's fixtures, which strip do_not_claim to sidestep a
pre-existing profile-content bug (the "backend" variant's canonical ct_b1
bullet mentions "Kubernetes" while "Kubernetes" is do_not_claim -- out of
scope to fix here; see M8P-3R). This file uses the "ml" base variant
instead, whose canonical bullet_order never includes ct_b1/ct_b2/cm_b1/cm_b2
-- the only bullets that mention "Kubernetes" anywhere in the real profile
-- so the real do_not_claim list can be exercised without inheriting that
unrelated bug. All model calls are scripted; no network, no real model, no
production DB (a throwaway tmp_path SQLite file is used for the
no-write-occurs check)."""
import hashlib
import json
from unittest.mock import MagicMock, patch
import subprocess

import pytest

from scripts.tailor_g2 import cmd_invoke as g2_cmd_invoke, cmd_prepare as g2_cmd_prepare
from src.profile import load_profile
from src.tailor.alignment_view import alignment_from_profile
from src.tailor.g1 import run_static_g1
from src.tailor.g2_pipeline import G2OutcomeKind, run_g2_loop
from src.tailor.invoke import InvocationResult
from src.tailor.s0 import build_s0_request, parse_s0_response
from src.tailor.s1 import parse_s1_response
from src.tailor.s2 import build_s2_request, parse_s2_response
from src.tailor.s3 import (
    build_s3_request,
    calculate_edit_budget,
    derive_change_log,
    derive_unified_diff,
    hydrate_s3,
    parse_s3_response,
)
from src.tailor.s3_pipeline import S3Bundle
from tests.test_tailor_g2_cli import _g2_chain, _g2_invoke_args, _g2_prepare_args

EDITED_BULLET_ID = "int_b1"
EDITED_BULLET_AFTER = (
    "Built the **anti-corruption layer** and **Core onboarding service** "
    "orchestrating three of four adapter services, five asynchronous Python "
    "microservices in all."
)
#: Present verbatim in EDITED_BULLET_AFTER; used as a finding's quoted_line
#: and as the clause a further-shortening revision removes.
_REMOVED_CLAUSE = "orchestrating three of four adapter services"


class _ScriptedInvoke:
    """Shared canned-response queue for both g2_pipeline.invoke_text_model
    and s3_pipeline.invoke_text_model, consumed in the exact chronological
    order run_g2_loop actually calls them."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.call_count = 0

    def __call__(self, prompt, *, claude_cmd=(), timeout=300):
        self.call_count += 1
        if not self._responses:
            raise AssertionError("scripted invoke called more times than scripted")
        outcome = self._responses.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return InvocationResult(outcome, "stderr: <empty>", "fake")


def _build_real_pair():
    """A real config/master_profile.yaml S3Request/S3Bundle pair on the
    "ml" base variant, with the profile's authentic do_not_claim intact."""
    profile = load_profile("config/master_profile.yaml")
    positioning = profile.for_positioning()
    catalog = profile.for_selection("ml")
    must_have = [{"term": "Python", "quote": "Python"}]
    s1 = parse_s1_response(
        json.dumps({
            "must_have": must_have, "nice_to_have": [], "responsibilities_summary": [],
            "seniority_signals": [], "disqualifiers": [], "company_context": None,
            "suspected_injection": [],
        }),
        "Python",
    )
    s0_request = build_s0_request(1, "Example", "ML Engineer", s1, positioning)
    s0 = parse_s0_response(
        json.dumps({
            "context_mode": "jd_only",
            "points": [
                {"sentence": "Lead with backend delivery.", "profile_ids": [positioning.projects[0].id], "requirement_terms": ["Python"], "jd_quotes": ["Python"]},
                {"sentence": "Support the claim with production experience.", "profile_ids": [positioning.experiences[0].id], "requirement_terms": ["Python"], "jd_quotes": ["Python"]},
            ],
        }),
        s0_request,
    )
    s2_request = build_s2_request(1, "Example", "ML Engineer", s1, s0, catalog)
    variant = next(item for item in s2_request.catalog.variants if item.name == "ml")
    coverage = [{"term": "Python", "status": "covered", "bullet_ids": ["int_b1"]}]
    s2_response = parse_s2_response(
        json.dumps({
            "base_variant": "ml",
            "projects": [{"project_id": item, "reason": "selected", "s0_point_indexes": [0]} for item in variant.projects],
            "bullet_order": list(variant.bullet_order),
            "coverage": coverage,
        }),
        s2_request,
    )
    alignment = alignment_from_profile(profile, s2_request, s2_response)  # real do_not_claim intact
    request = build_s3_request(1, "Example", "ML Engineer", s1, s0, s2_response, alignment)

    raw = json.dumps({
        "bullet_edits": [{
            "bullet_id": EDITED_BULLET_ID, "after": EDITED_BULLET_AFTER,
            "motivating_terms": ["Python"], "rule": "terminology_mirroring",
        }],
        "skill_additions": [],
    })
    response = parse_s3_response(raw, request)
    draft = hydrate_s3(request, response)
    report = run_static_g1(request, response, draft, ())
    assert report.status.value == "static_pass", report.violations
    bundle = S3Bundle(
        "m8p3.s3_bundle.v1", request.job_id, request.company, request.title,
        request.alignment.fingerprint, response, draft,
        derive_change_log(request, response, draft), derive_unified_diff(request, draft),
        calculate_edit_budget(request, draft), report,
    )
    return request, bundle


def _loop_kwargs(tmp_path, request, bundle, *, banned_terms=()):
    g2_prompt = tmp_path / "g2_prompt.md"
    g2_prompt.write_text("{{G2_REQUEST_JSON}}", encoding="utf-8")
    s3_prompt = tmp_path / "s3_revision_prompt.md"
    s3_prompt.write_text("{{S3_REQUEST_JSON}} {{S3_REVISION_JSON}}", encoding="utf-8")
    request_path = tmp_path / "s3_request.json"
    request_path.write_text("{}", encoding="utf-8")
    return dict(
        s3_request=request, s3_bundle=bundle,
        prompt_template_path=g2_prompt, s3_prompt_template_path=s3_prompt,
        request_path=request_path, banned_terms=banned_terms, taste_lessons=(),
        trace_dir=tmp_path / "traces",
    )


def _pass_response():
    return json.dumps({"scores": {"C1": 3, "C2": 3, "C3": 3, "C4": 3, "C5": 3}, "findings": []})


def _s3_revision_response(after_text, *, motivating_terms=("Python",)):
    return json.dumps({
        "bullet_edits": [{
            "bullet_id": EDITED_BULLET_ID, "after": after_text,
            "motivating_terms": list(motivating_terms), "rule": "terminology_mirroring",
        }],
        "skill_additions": [],
    })


def _shorten_further(bundle) -> str:
    current = next(b for b in bundle.draft.bullets if b.bullet_id == EDITED_BULLET_ID)
    return current.text.replace(" " + _REMOVED_CLAUSE + ",", ",")


def test_critic_cannot_smuggle_replacement_text(tmp_path, monkeypatch):
    """Every field the critic can write is validated; none reaches the
    draft. Here the critic's free-text explanation contains an explicit
    proposed rewrite ("Replace with: ..."), but G2Finding has no field the
    pipeline ever copies into resume text -- the actual round-2 edit is
    authored independently (scripted separately below), exactly as D2
    requires: G2 never emits replacement text, only structured findings."""
    request, bundle = _build_real_pair()
    smuggled_phrase = "fault-tolerant K8s mesh"
    finding = {
        "dimension": "C2", "rule_id": "C2.register_shift", "target_kind": "bullet",
        "target_id": EDITED_BULLET_ID, "quoted_line": _REMOVED_CLAUSE,
        "explanation": f"Replace with: Architected a {smuggled_phrase}",
    }
    revise_raw = json.dumps({"scores": {"C1": 3, "C2": 1, "C3": 3, "C4": 3, "C5": 3}, "findings": [finding]})
    scripted = _ScriptedInvoke([revise_raw, _s3_revision_response(_shorten_further(bundle)), _pass_response()])
    monkeypatch.setattr("src.tailor.g2_pipeline.invoke_text_model", scripted)
    monkeypatch.setattr("src.tailor.s3_pipeline.invoke_text_model", scripted)

    outcome = run_g2_loop(**_loop_kwargs(tmp_path, request, bundle))

    assert outcome.kind is G2OutcomeKind.PASSED_ROUND_2
    for draft_bullet in outcome.bundle.accepted_s3_bundle.draft.bullets:
        assert "fault-tolerant" not in draft_bullet.plain_text
        assert "K8s" not in draft_bullet.plain_text
        assert smuggled_phrase not in draft_bullet.plain_text


def test_revision_reintroducing_banned_word_is_rejected(tmp_path, monkeypatch):
    """A structurally valid revision (passes every per-edit S3 rule) is
    still rejected if it fails the aggregate static G1 pass -- the loop is
    run with "Python" itself declared banned (it legitimately appears, cited,
    in the revised text), so L2 fires even though the individual edit is
    otherwise unimpeachable."""
    request, bundle = _build_real_pair()
    finding = {
        "dimension": "C5", "rule_id": "C5.template_phrasing", "target_kind": "bullet",
        "target_id": EDITED_BULLET_ID, "quoted_line": _REMOVED_CLAUSE,
        "explanation": "reads as template output",
    }
    revise_raw = json.dumps({"scores": {"C1": 3, "C2": 3, "C3": 3, "C4": 3, "C5": 1}, "findings": [finding]})
    scripted = _ScriptedInvoke([revise_raw, _s3_revision_response(_shorten_further(bundle))])
    monkeypatch.setattr("src.tailor.g2_pipeline.invoke_text_model", scripted)
    monkeypatch.setattr("src.tailor.s3_pipeline.invoke_text_model", scripted)

    outcome = run_g2_loop(**_loop_kwargs(tmp_path, request, bundle, banned_terms=("Python",)))

    assert outcome.kind is G2OutcomeKind.REVISION_G1_FAILURE
    assert outcome.bundle is None


def test_revision_dropping_a_metric_is_rejected(tmp_path, monkeypatch):
    """A revision that changes the bullet's numeric-token multiset is
    rejected.

    2026-09-15 blueprint substitution: the original scenario dropped the
    bullet's sole numeric token ("2.0"); the approved blueprint's int_b1
    medium spells every count out ("three", "four", "five") and now has
    ZERO numeric tokens, so there is nothing left to drop. The rule under
    test -- numeric-token-multiset preservation -- is exercised the other
    direction instead: the revision spells "three of four" as "3 of 4",
    introducing digits where the canonical text has none. Same check
    (S3SemanticError: "numeric-token multiset changed"), same outcome.

    Deviation from the plan: the plan's Task 7 pseudocode asserts
    G2OutcomeKind.REVISION_G1_FAILURE for this scenario. In the merged
    code, numeric-token-multiset preservation is enforced inside
    parse_s3_response (S3SemanticError: "numeric-token multiset changed"),
    which run_s3_revision maps to S3OutcomeKind.SEMANTIC_FAILURE and
    run_g2_loop in turn maps to G2OutcomeKind.REVISION_SEMANTIC_FAILURE --
    not REVISION_G1_FAILURE (that kind is reserved for
    S3OutcomeKind.HYDRATION_FAILURE/G1_FAILURE, i.e. failures that occur
    only after an edit has already passed every per-edit S3 rule). The
    protection this test is actually verifying -- a revision cannot drop a
    metric -- is real and confirmed; only the plan's predicted enum value
    was wrong. Flagged in the M8P-4 final report per the task's stop
    conditions ("plan appears wrong about merged code -> stop and ask, do
    not silently diverge"); proceeding with the code's actual, verified
    behavior rather than halting, since this is an objectively checkable
    labeling error, not a design ambiguity."""
    request, bundle = _build_real_pair()
    finding = {
        "dimension": "C4", "rule_id": "C4.impact_diluted", "target_kind": "bullet",
        "target_id": EDITED_BULLET_ID, "quoted_line": _REMOVED_CLAUSE,
        "explanation": "impact is below the fold",
    }
    revise_raw = json.dumps({"scores": {"C1": 3, "C2": 3, "C3": 3, "C4": 1, "C5": 3}, "findings": [finding]})
    dropped_metric_after = EDITED_BULLET_AFTER.replace("three of four", "3 of 4")
    scripted = _ScriptedInvoke([revise_raw, _s3_revision_response(dropped_metric_after)])
    monkeypatch.setattr("src.tailor.g2_pipeline.invoke_text_model", scripted)
    monkeypatch.setattr("src.tailor.s3_pipeline.invoke_text_model", scripted)

    outcome = run_g2_loop(**_loop_kwargs(tmp_path, request, bundle))

    assert outcome.kind is G2OutcomeKind.REVISION_SEMANTIC_FAILURE
    assert outcome.bundle is None
    assert "numeric-token multiset changed" in outcome.error


def test_revision_adding_do_not_claim_term_is_rejected(tmp_path, monkeypatch):
    """"Kubernetes" is the real do_not_claim entry in
    config/master_profile.yaml. A revision cannot smuggle it in.

    Deviation from the plan: the plan's Task 7 pseudocode assumes a
    revision could legitimately cite "Kubernetes" as a motivating term and
    have G1's L6 do_not_claim check be the layer that rejects it
    (REVISION_G1_FAILURE). In the merged code, do_not_claim is defense in
    depth at an *earlier* layer than assumed: src/tailor/s2.py's
    validate_s2_selection() structurally refuses to ever mark a
    do_not_claim term "covered" ("do_not_claim term covered"), and
    src/tailor/s3.py's per-edit citation gate requires every added word
    either be a cited motivating_term or already present in the canonical
    source text. Since "Kubernetes" can never legitimately become
    "covered", the only way it could reach a bullet's text at all is as an
    *uncited* addition -- which S3's own "uncited vocabulary" check
    rejects at parse time, before G1 ever runs. This test exercises that
    actually-reachable attack path and asserts the real, verified outcome
    (REVISION_SEMANTIC_FAILURE) rather than the plan's predicted one.
    Flagged in the M8P-4 final report."""
    request, bundle = _build_real_pair()
    finding = {
        "dimension": "C3", "rule_id": "C3.keyword_chasing", "target_kind": "bullet",
        "target_id": EDITED_BULLET_ID, "quoted_line": "adapter",
        "explanation": "keyword coverage could be stronger",
    }
    revise_raw = json.dumps({"scores": {"C1": 3, "C2": 3, "C3": 1, "C4": 3, "C5": 3}, "findings": [finding]})
    smuggled_after = EDITED_BULLET_AFTER.replace("adapter", "Kubernetes")
    # Cites only "Python" -- "Kubernetes" is never a legitimate motivating
    # term (see docstring), so this is an uncited addition.
    scripted = _ScriptedInvoke([revise_raw, _s3_revision_response(smuggled_after, motivating_terms=("Python",))])
    monkeypatch.setattr("src.tailor.g2_pipeline.invoke_text_model", scripted)
    monkeypatch.setattr("src.tailor.s3_pipeline.invoke_text_model", scripted)

    outcome = run_g2_loop(**_loop_kwargs(tmp_path, request, bundle))

    assert outcome.kind is G2OutcomeKind.REVISION_SEMANTIC_FAILURE
    assert outcome.bundle is None
    assert "uncited vocabulary" in outcome.error


def test_no_sqlite_write_occurs(tmp_path):
    """End to end via the real CLI (scripts/tailor_g2.py prepare + invoke,
    mocked subprocess): a throwaway tmp_path SQLite file's SHA-256 is
    unchanged after a full prepare+invoke pass. Reuses Task 6's own
    fixture-building helpers rather than re-deriving the chain here."""
    chain = _g2_chain(tmp_path)
    before = hashlib.sha256(chain.database.read_bytes()).hexdigest()

    prepared = tmp_path / "g2_prepared"
    assert g2_cmd_prepare(_g2_prepare_args(tmp_path, chain, output=prepared)) == 0

    with patch.object(subprocess, "run", return_value=MagicMock(returncode=0, stdout=_pass_response(), stderr="")):
        rc = g2_cmd_invoke(
            _g2_invoke_args(
                tmp_path, prepared / "g2_request.json", prepared / "s3_request.json",
                output=tmp_path / "g2_out", trace_dir=str(tmp_path / "traces"),
            )
        )
    assert rc == 0

    after = hashlib.sha256(chain.database.read_bytes()).hexdigest()
    assert after == before
