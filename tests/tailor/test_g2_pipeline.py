"""Bounded G2 revision loop (M8P-4 Task 5). All model calls are scripted
mocks; no network, no real model, no pdflatex."""
import json

import pytest

from src.tailor.g2 import G2Verdict
from src.tailor.g2_pipeline import G2OutcomeKind, run_g2_loop
from src.tailor.invoke import InvocationError, InvocationResult
from tests.tailor.conftest import EDITED_BULLET_ID


class _ScriptedInvoke:
    """A queue of canned model responses shared across both
    src.tailor.g2_pipeline.invoke_text_model and
    src.tailor.s3_pipeline.invoke_text_model, so the call order across the
    critic/revision interleaving is exactly what run_g2_loop actually
    produces (not a per-module count)."""

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


@pytest.fixture
def loop_kwargs(tmp_path, s3_pair_with_bundle):
    request, bundle = s3_pair_with_bundle
    g2_prompt = tmp_path / "g2_prompt.md"
    g2_prompt.write_text("{{G2_REQUEST_JSON}}", encoding="utf-8")
    s3_prompt = tmp_path / "s3_revision_prompt.md"
    s3_prompt.write_text("{{S3_REQUEST_JSON}} {{S3_REVISION_JSON}}", encoding="utf-8")
    request_path = tmp_path / "s3_request.json"
    request_path.write_text("{}", encoding="utf-8")
    return dict(
        s3_request=request,
        s3_bundle=bundle,
        prompt_template_path=g2_prompt,
        s3_prompt_template_path=s3_prompt,
        request_path=request_path,
        banned_terms=(),
        taste_lessons=(),
        trace_dir=tmp_path / "traces",
    )


def _pass_response(**overrides):
    scores = {"C1": 3, "C2": 3, "C3": 3, "C4": 3, "C5": 3}
    scores.update(overrides)
    return json.dumps({"scores": scores, "findings": []})


def _revise_response(quoted_line: str, *, dimension="C2", rule_id="C2.register_shift"):
    # A score of 1 (not 2) is required to force REVISE: the verdict rule is
    # PASS iff C1==3 and min(C2..C5) >= 2, so a score of exactly 2 already
    # passes -- it only requires a finding, it does not fail the verdict.
    scores = {"C1": 3, "C2": 3, "C3": 3, "C4": 3, "C5": 3}
    scores[dimension] = 1
    finding = {
        "dimension": dimension,
        "rule_id": rule_id,
        "target_kind": "bullet",
        "target_id": EDITED_BULLET_ID,
        "quoted_line": quoted_line,
        "explanation": "synthetic finding for M8P-4 loop tests",
    }
    return json.dumps({"scores": scores, "findings": [finding]})


def _s3_revision_response(after_text: str, *, motivating_terms=("Python",)):
    return json.dumps({
        "bullet_edits": [{
            "bullet_id": EDITED_BULLET_ID,
            "after": after_text,
            "motivating_terms": list(motivating_terms),
            "rule": "terminology_mirroring",
        }],
        "skill_additions": [],
    })


#: The clause this fixture's second-round edit removes -- also used as the
#: round-1 finding's quoted_line so unresolved_findings() correctly detects
#: the revision actually changed the text the finding named. 2026-09-15
#: blueprint: int_b1's medium now has no numeric tokens at all (every count
#: is spelled out), so there is no "metric-bearing parenthetical" to
#: preserve; the invariant this fixture exercises -- the edit changes the
#: named clause while the rest of the bullet survives -- still holds.
_REMOVED_CLAUSE = "orchestrating three of four adapter services"


def _shorten_further(bundle) -> str:
    """A second, further-shortened edit of the already-edited bullet: drop
    the middle clause, preserving the leading verb and the (empty)
    numeric-token multiset."""
    current = next(b for b in bundle.draft.bullets if b.bullet_id == EDITED_BULLET_ID)
    return current.text.replace(" " + _REMOVED_CLAUSE + ",", ",")


def _reordered_edit(request) -> str:
    """A same-length-or-shorter, verb-and-metric-preserving edit that
    reorders (never adds/removes) the canonical bullet's own words --
    reordering cannot introduce "uncited vocabulary" because every token
    already existed in the source. Used to prove static G1 still runs (and
    can still reject) a structurally-valid revision."""
    source = next(b for b in request.alignment.bullets if b.bullet_id == EDITED_BULLET_ID)
    words = source.plain_text.split()
    verb, rest = words[0], words[1:]
    return " ".join([verb, *reversed(rest)])


def test_pass_on_round_one_uses_one_model_call(loop_kwargs, monkeypatch):
    scripted = _ScriptedInvoke([_pass_response()])
    monkeypatch.setattr("src.tailor.g2_pipeline.invoke_text_model", scripted)
    monkeypatch.setattr("src.tailor.s3_pipeline.invoke_text_model", scripted)

    outcome = run_g2_loop(**loop_kwargs)
    assert outcome.kind is G2OutcomeKind.PASSED_ROUND_1
    assert outcome.bundle.model_calls == 1
    assert outcome.bundle.rounds_used == 1
    assert outcome.bundle.verdict is G2Verdict.PASS


def test_revision_accepted_then_pass_on_round_two(loop_kwargs, monkeypatch, s3_pair_with_bundle):
    _, bundle = s3_pair_with_bundle
    revised_after = _shorten_further(bundle)
    scripted = _ScriptedInvoke([
        _revise_response(_REMOVED_CLAUSE),
        _s3_revision_response(revised_after),
        _pass_response(),
    ])
    monkeypatch.setattr("src.tailor.g2_pipeline.invoke_text_model", scripted)
    monkeypatch.setattr("src.tailor.s3_pipeline.invoke_text_model", scripted)

    outcome = run_g2_loop(**loop_kwargs)
    assert outcome.kind is G2OutcomeKind.PASSED_ROUND_2
    assert outcome.bundle.rounds_used == 2
    assert outcome.bundle.model_calls == 3


def test_open_flags_after_two_failing_rounds(loop_kwargs, monkeypatch, s3_pair_with_bundle):
    _, bundle = s3_pair_with_bundle
    revised_after = _shorten_further(bundle)
    scripted = _ScriptedInvoke([
        _revise_response(_REMOVED_CLAUSE),
        _s3_revision_response(revised_after),
        _revise_response("Python microservices"),
    ])
    monkeypatch.setattr("src.tailor.g2_pipeline.invoke_text_model", scripted)
    monkeypatch.setattr("src.tailor.s3_pipeline.invoke_text_model", scripted)

    outcome = run_g2_loop(**loop_kwargs)
    assert outcome.kind is G2OutcomeKind.OPEN_FLAGS
    assert outcome.bundle.open_findings
    assert outcome.bundle.verdict is G2Verdict.OPEN_FLAGS


def test_noop_revision_short_circuits(loop_kwargs, monkeypatch, s3_pair_with_bundle):
    _, bundle = s3_pair_with_bundle
    quote = "five asynchronous Python microservices"
    current_after = next(b.text for b in bundle.draft.bullets if b.bullet_id == EDITED_BULLET_ID)
    scripted = _ScriptedInvoke([
        _revise_response(quote),
        _s3_revision_response(current_after),
    ])
    monkeypatch.setattr("src.tailor.g2_pipeline.invoke_text_model", scripted)
    monkeypatch.setattr("src.tailor.s3_pipeline.invoke_text_model", scripted)

    outcome = run_g2_loop(**loop_kwargs)
    assert outcome.kind is G2OutcomeKind.REVISION_NOOP
    assert outcome.bundle is None
    assert scripted.call_count == 2


def test_revision_failing_g1_preserves_original_bundle(loop_kwargs, monkeypatch, s3_pair_with_bundle):
    """A structurally valid revision (passes every per-edit S3 rule) is
    still rejected if it fails the aggregate static G1 pass -- here, the
    loop is run with "Python" itself declared banned, so L2 fires even
    though the individual edit is otherwise unimpeachable. bundle_0 is
    never touched; run_g2_loop returns no G2Bundle for this outcome."""
    _, bundle = s3_pair_with_bundle
    loop_kwargs = {**loop_kwargs, "banned_terms": ("Python",)}
    scripted = _ScriptedInvoke([
        _revise_response(_REMOVED_CLAUSE),
        _s3_revision_response(_shorten_further(bundle)),
    ])
    monkeypatch.setattr("src.tailor.g2_pipeline.invoke_text_model", scripted)
    monkeypatch.setattr("src.tailor.s3_pipeline.invoke_text_model", scripted)

    outcome = run_g2_loop(**loop_kwargs)
    assert outcome.kind is G2OutcomeKind.REVISION_G1_FAILURE
    assert outcome.bundle is None


def test_edit_budget_is_recomputed_against_canonical_not_round_one(loop_kwargs, monkeypatch, s3_pair_with_bundle):
    """calculate_edit_budget() inside the revision's static G1 pass must be
    computed against the canonical alignment (the same fixed denominator
    every round), not against round-1's already-edited draft -- proven here
    by asserting the accepted revision's edit_budget.base_tokens equals
    bundle_0's, even though the bullet text changed twice."""
    request, bundle = s3_pair_with_bundle
    revised_after = _shorten_further(bundle)
    scripted = _ScriptedInvoke([
        _revise_response(_REMOVED_CLAUSE),
        _s3_revision_response(revised_after),
        _pass_response(),
    ])
    monkeypatch.setattr("src.tailor.g2_pipeline.invoke_text_model", scripted)
    monkeypatch.setattr("src.tailor.s3_pipeline.invoke_text_model", scripted)

    outcome = run_g2_loop(**loop_kwargs)
    assert outcome.kind is G2OutcomeKind.PASSED_ROUND_2
    revised_bundle = outcome.bundle.accepted_s3_bundle
    assert revised_bundle.edit_budget.base_tokens == bundle.edit_budget.base_tokens


def test_invocation_failure_writes_trace_when_raw_output_exists(loop_kwargs, monkeypatch):
    scripted = _ScriptedInvoke([InvocationError("nonzero exit", raw_stdout="partial garbled output", model="fake")])
    monkeypatch.setattr("src.tailor.g2_pipeline.invoke_text_model", scripted)
    monkeypatch.setattr("src.tailor.s3_pipeline.invoke_text_model", scripted)

    outcome = run_g2_loop(**loop_kwargs)
    assert outcome.kind is G2OutcomeKind.INVOCATION_FAILURE
    assert outcome.trace_paths
    assert outcome.trace_paths[0].exists()


def test_invocation_failure_without_raw_output_writes_no_trace(loop_kwargs, monkeypatch):
    scripted = _ScriptedInvoke([InvocationError("timeout", raw_stdout="", model="fake")])
    monkeypatch.setattr("src.tailor.g2_pipeline.invoke_text_model", scripted)
    monkeypatch.setattr("src.tailor.s3_pipeline.invoke_text_model", scripted)

    outcome = run_g2_loop(**loop_kwargs)
    assert outcome.kind is G2OutcomeKind.INVOCATION_FAILURE
    assert outcome.trace_paths == ()


def test_revision_invocation_failure_maps_correctly(loop_kwargs, monkeypatch):
    scripted = _ScriptedInvoke([
        _revise_response("five asynchronous Python microservices"),
        InvocationError("revision model down", raw_stdout="", model="fake"),
    ])
    monkeypatch.setattr("src.tailor.g2_pipeline.invoke_text_model", scripted)
    monkeypatch.setattr("src.tailor.s3_pipeline.invoke_text_model", scripted)

    outcome = run_g2_loop(**loop_kwargs)
    assert outcome.kind is G2OutcomeKind.REVISION_INVOCATION_FAILURE
    assert outcome.bundle is None


def test_revision_parse_failure_maps_correctly(loop_kwargs, monkeypatch):
    scripted = _ScriptedInvoke([
        _revise_response("five asynchronous Python microservices"),
        "not json at all",
    ])
    monkeypatch.setattr("src.tailor.g2_pipeline.invoke_text_model", scripted)
    monkeypatch.setattr("src.tailor.s3_pipeline.invoke_text_model", scripted)

    outcome = run_g2_loop(**loop_kwargs)
    assert outcome.kind is G2OutcomeKind.REVISION_PARSE_FAILURE


def test_revision_semantic_failure_when_out_of_scope_bullet_edited(loop_kwargs, monkeypatch):
    out_of_scope = json.dumps({
        "bullet_edits": [{
            "bullet_id": "int_b2",
            "after": "Owned an unrelated bullet nobody flagged.",
            "motivating_terms": ["Python"],
            "rule": "terminology_mirroring",
        }],
        "skill_additions": [],
    })
    scripted = _ScriptedInvoke([
        _revise_response("five asynchronous Python microservices"),
        out_of_scope,
    ])
    monkeypatch.setattr("src.tailor.g2_pipeline.invoke_text_model", scripted)
    monkeypatch.setattr("src.tailor.s3_pipeline.invoke_text_model", scripted)

    outcome = run_g2_loop(**loop_kwargs)
    assert outcome.kind in (G2OutcomeKind.REVISION_SEMANTIC_FAILURE, G2OutcomeKind.REVISION_PARSE_FAILURE)


def test_bundle_round_trips_strictly(s3_pair_with_bundle):
    from src.tailor.g2 import G2Verdict as _Verdict
    from src.tailor.g2 import build_g2_request, parse_g2_response
    from src.tailor.g2_pipeline import G2Bundle, G2Round, g2_bundle_to_dict, parse_g2_bundle

    request, bundle = s3_pair_with_bundle
    request_obj = build_g2_request(request, bundle, round_index=1, banned_terms=(), taste_lessons=())
    response = parse_g2_response(_pass_response(), request_obj)
    round_record = G2Round(round_index=1, response=response, verdict=_Verdict.PASS, trace_path=None)
    passing_bundle = G2Bundle(
        schema_version="m8p4.g2_bundle.v1",
        job_id=bundle.job_id,
        company=bundle.company,
        title=bundle.title,
        alignment_fingerprint=bundle.alignment_fingerprint,
        accepted_s3_bundle=bundle,
        rounds=(round_record,),
        verdict=_Verdict.PASS,
        open_findings=(),
        rounds_used=1,
        model_calls=1,
    )
    assert parse_g2_bundle(g2_bundle_to_dict(passing_bundle)) == passing_bundle
