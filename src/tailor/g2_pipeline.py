"""Bounded G2 revision loop (M8P-4 Task 5): critic -> [S3 revision -> critic]
-> terminal outcome. Publication is the caller's job (Task 6); this module
returns a value and writes only I11 traces.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from src.llm_trace import write_trace
from src.tailor.g1 import parse_g1_report
from src.tailor.g2 import (
    MAX_ROUNDS,
    G2Finding,
    G2ParseError,
    G2Response,
    G2SemanticError,
    G2Verdict,
    build_g2_prompt,
    build_g2_request,
    evaluate_verdict,
    g2_response_to_dict,
    parse_g2_response,
    unresolved_findings,
)
from src.tailor.g2 import _finding_to_dict, _object, _parse_finding_list, _parse_scores, _string  # noqa: F401 -- internal reuse, same feature family
from src.tailor.invoke import DEFAULT_CLAUDE_CMD, DEFAULT_TIMEOUT_SECONDS, InvocationError, invoke_text_model
from src.tailor.providers import ModelCommand, trace_model_label
from src.tailor.s3 import (
    BulletEdit,
    S3EditRule,
    S3Request,
    S3Response,
    S3RevisionContext,
    SkillAddition,
    parse_change_log,
    parse_edit_budget,
    parse_tailored_draft,
)
from src.tailor.s3_pipeline import S3Bundle, S3OutcomeKind, run_s3_revision

TRACE_INVOCATION_TYPE = "tailoring_g2"


class G2OutcomeKind(str, Enum):
    INVOCATION_FAILURE = "invocation_failure"
    PARSE_FAILURE = "parse_failure"
    SEMANTIC_FAILURE = "semantic_failure"
    REVISION_INVOCATION_FAILURE = "revision_invocation_failure"
    REVISION_PARSE_FAILURE = "revision_parse_failure"
    REVISION_SEMANTIC_FAILURE = "revision_semantic_failure"
    REVISION_NOOP = "revision_noop"
    REVISION_G1_FAILURE = "revision_g1_failure"
    PASSED_ROUND_1 = "passed_round_1"
    PASSED_ROUND_2 = "passed_round_2"
    OPEN_FLAGS = "open_flags"


@dataclass(frozen=True)
class G2Round:
    round_index: int
    response: G2Response
    verdict: G2Verdict
    trace_path: Path | None


@dataclass(frozen=True)
class G2Bundle:
    schema_version: str
    job_id: int
    company: str
    title: str
    alignment_fingerprint: str
    accepted_s3_bundle: S3Bundle
    rounds: tuple[G2Round, ...]
    verdict: G2Verdict
    open_findings: tuple[G2Finding, ...]
    rounds_used: int
    model_calls: int


@dataclass(frozen=True)
class G2Outcome:
    kind: G2OutcomeKind
    bundle: G2Bundle | None
    error: str | None
    trace_paths: tuple[Path, ...]


_G2_BUNDLE_SCHEMA_VERSION = "m8p4.g2_bundle.v1"


def _trace(request_path: Path, prompt_template_path: Path, raw: str, model: str, trace_dir: Path) -> Path | None:
    if not raw.strip():
        return None
    return write_trace(
        invocation_type=TRACE_INVOCATION_TYPE,
        input_paths=[request_path],
        raw_output=raw,
        prompt_path=prompt_template_path,
        model=model,
        trace_dir=trace_dir,
    )


def _revised_text_by_target(bundle: S3Bundle) -> dict[str, str]:
    """Maps every possible G2 finding target_id to its current text, so a
    revision's progress against prior findings can be checked before
    spending a second critic call. Bullet targets map to plain_text; skill-
    addition targets map to the added term itself (matching G2's
    `f"{category}:{term}"` target_id convention and its exact-match rule
    for skill-addition quotes)."""
    mapping = {item.bullet_id: item.plain_text for item in bundle.draft.bullets}
    for entry in bundle.change_log:
        if entry.location.startswith("skills:"):
            category = entry.location.split(":", 1)[1]
            mapping[f"{category}:{entry.after}"] = entry.after
    return mapping


def run_g2_loop(
    s3_request: S3Request,
    s3_bundle: S3Bundle,
    *,
    prompt_template_path: Path,
    s3_prompt_template_path: Path,
    request_path: Path,
    banned_terms: tuple[str, ...],
    taste_lessons: tuple[str, ...],
    command: ModelCommand | None = None,
    model_command: ModelCommand | None = None,
    claude_cmd: tuple[str, ...] = DEFAULT_CLAUDE_CMD,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    trace_dir: Path = Path("data/traces"),
    max_rounds: int = MAX_ROUNDS,
) -> G2Outcome:
    effective_cmd = model_command if model_command is not None else command
    trace_paths: list[Path] = []
    model_calls = 0
    rounds: tuple[G2Round, ...] = ()
    current_bundle = s3_bundle
    prior_findings: tuple[G2Finding, ...] = ()
    round_index = 1

    while True:
        g2_request = build_g2_request(
            s3_request, current_bundle, round_index=round_index,
            banned_terms=banned_terms, taste_lessons=taste_lessons,
            prior_findings=prior_findings,
        )
        g2_template = Path(prompt_template_path).read_text(encoding="utf-8")
        g2_prompt = build_g2_prompt(g2_template, g2_request)
        try:
            if effective_cmd is not None:
                g2_result = invoke_text_model(g2_prompt, command=effective_cmd, timeout=timeout)
            else:
                g2_result = invoke_text_model(g2_prompt, claude_cmd=claude_cmd, timeout=timeout)
        except InvocationError as exc:
            model_calls += 1
            trace_model = exc.model or (trace_model_label(effective_cmd) if effective_cmd else (claude_cmd[0] if claude_cmd else ""))
            trace_path = _trace(request_path, prompt_template_path, exc.raw_stdout, trace_model, trace_dir)
            if trace_path is not None:
                trace_paths.append(trace_path)
            return G2Outcome(G2OutcomeKind.INVOCATION_FAILURE, None, str(exc), tuple(trace_paths))
        model_calls += 1
        critic_trace_path = _trace(request_path, prompt_template_path, g2_result.raw_stdout, g2_result.model, trace_dir)
        if critic_trace_path is not None:
            trace_paths.append(critic_trace_path)

        try:
            g2_response = parse_g2_response(g2_result.raw_stdout, g2_request)
        except G2ParseError as exc:
            return G2Outcome(G2OutcomeKind.PARSE_FAILURE, None, str(exc), tuple(trace_paths))
        except G2SemanticError as exc:
            return G2Outcome(G2OutcomeKind.SEMANTIC_FAILURE, None, str(exc), tuple(trace_paths))

        verdict = evaluate_verdict(g2_response, round_index=round_index, max_rounds=max_rounds)
        rounds = rounds + (G2Round(round_index, g2_response, verdict, critic_trace_path),)

        if verdict is G2Verdict.PASS:
            outcome_kind = G2OutcomeKind.PASSED_ROUND_1 if round_index == 1 else G2OutcomeKind.PASSED_ROUND_2
            bundle = G2Bundle(
                _G2_BUNDLE_SCHEMA_VERSION, s3_request.job_id, s3_request.company, s3_request.title,
                current_bundle.alignment_fingerprint, current_bundle, rounds, verdict, (), round_index, model_calls,
            )
            return G2Outcome(outcome_kind, bundle, None, tuple(trace_paths))

        if verdict is G2Verdict.OPEN_FLAGS:
            bundle = G2Bundle(
                _G2_BUNDLE_SCHEMA_VERSION, s3_request.job_id, s3_request.company, s3_request.title,
                current_bundle.alignment_fingerprint, current_bundle, rounds, verdict,
                g2_response.findings, round_index, model_calls,
            )
            return G2Outcome(G2OutcomeKind.OPEN_FLAGS, bundle, None, tuple(trace_paths))

        # verdict is REVISE: attempt exactly one bounded S3 revision.
        revision_context = S3RevisionContext(round_index=round_index, findings=g2_response.findings)
        s3_outcome = run_s3_revision(
            s3_request, current_bundle.response, context=revision_context,
            prompt_template_path=s3_prompt_template_path, request_path=request_path,
            banned_terms=banned_terms, command=effective_cmd, claude_cmd=claude_cmd, timeout=timeout, trace_dir=trace_dir,
        )
        model_calls += 1
        if s3_outcome.trace_path is not None:
            trace_paths.append(s3_outcome.trace_path)

        if s3_outcome.kind is S3OutcomeKind.INVOCATION_FAILURE:
            return G2Outcome(G2OutcomeKind.REVISION_INVOCATION_FAILURE, None, s3_outcome.error, tuple(trace_paths))
        if s3_outcome.kind is S3OutcomeKind.PARSE_FAILURE:
            return G2Outcome(G2OutcomeKind.REVISION_PARSE_FAILURE, None, s3_outcome.error, tuple(trace_paths))
        if s3_outcome.kind is S3OutcomeKind.SEMANTIC_FAILURE:
            return G2Outcome(G2OutcomeKind.REVISION_SEMANTIC_FAILURE, None, s3_outcome.error, tuple(trace_paths))
        if s3_outcome.kind in (S3OutcomeKind.HYDRATION_FAILURE, S3OutcomeKind.G1_FAILURE):
            # No dedicated "revision hydration failure" kind exists in the
            # fixed G2OutcomeKind taxonomy; a broken hydration is the same
            # class of "the revised draft failed a downstream deterministic
            # check" as a G1 failure, so it is reported the same way.
            return G2Outcome(G2OutcomeKind.REVISION_G1_FAILURE, None, s3_outcome.error, tuple(trace_paths))

        # s3_outcome.kind is VALID: check for a no-op before a second critic call.
        revised_bundle = s3_outcome.bundle
        revised_text_by_target = _revised_text_by_target(revised_bundle)
        if unresolved_findings(g2_response.findings, revised_text_by_target) == g2_response.findings:
            return G2Outcome(
                G2OutcomeKind.REVISION_NOOP, None,
                "revision changed nothing the findings named", tuple(trace_paths),
            )

        current_bundle = revised_bundle
        prior_findings = g2_response.findings
        round_index += 1


# ---------------------------------------------------------------------------
# G2Bundle strict structural (de)serialization. No authoritative S3Request
# is available here (unlike S3's parse_s3_bundle, which recomputes against
# one) -- this is a pure structural round trip of what run_g2_loop already
# validated once at production time. accepted_s3_bundle's own strict
# revalidation against an authoritative S3Request is the caller's job (via
# src.tailor.s3_pipeline.parse_s3_bundle), exactly as scripts/tailor_s3.py
# already separates "structurally valid" from "authoritatively correct".
# ---------------------------------------------------------------------------


def _s3_response_to_dict(response: S3Response) -> dict[str, object]:
    from src.tailor.s3 import s3_response_to_dict

    return s3_response_to_dict(response)


def _parse_s3_response_structural(raw: object, path: str) -> S3Response:
    obj = _object(raw, {"bullet_edits", "skill_additions"}, path)
    edits = []
    for index, item in enumerate(obj["bullet_edits"]):
        edit_path = f"{path}.bullet_edits[{index}]"
        edit_obj = _object(item, {"bullet_id", "after", "motivating_terms", "rule"}, edit_path)
        edits.append(BulletEdit(
            _string(edit_obj["bullet_id"], f"{edit_path}.bullet_id"),
            _string(edit_obj["after"], f"{edit_path}.after"),
            tuple(_string(term, f"{edit_path}.motivating_terms[]") for term in edit_obj["motivating_terms"]),
            S3EditRule(edit_obj["rule"]),
        ))
    additions = []
    for index, item in enumerate(obj["skill_additions"]):
        addition_path = f"{path}.skill_additions[{index}]"
        addition_obj = _object(item, {"category", "term", "motivating_term"}, addition_path)
        additions.append(SkillAddition(
            _string(addition_obj["category"], f"{addition_path}.category"),
            _string(addition_obj["term"], f"{addition_path}.term"),
            _string(addition_obj["motivating_term"], f"{addition_path}.motivating_term"),
        ))
    return S3Response(tuple(edits), tuple(additions))


def _s3_bundle_to_dict(bundle: S3Bundle) -> dict[str, object]:
    from src.tailor.g1 import g1_report_to_dict
    from src.tailor.s3 import change_entry_to_dict, edit_budget_to_dict, tailored_draft_to_dict

    return {
        "schema_version": bundle.schema_version,
        "job_id": bundle.job_id,
        "company": bundle.company,
        "title": bundle.title,
        "alignment_fingerprint": bundle.alignment_fingerprint,
        "response": _s3_response_to_dict(bundle.response),
        "draft": tailored_draft_to_dict(bundle.draft),
        "change_log": [change_entry_to_dict(item) for item in bundle.change_log],
        "unified_diff": bundle.unified_diff,
        "edit_budget": edit_budget_to_dict(bundle.edit_budget),
        "g1": g1_report_to_dict(bundle.g1),
    }


_S3_BUNDLE_KEYS = {
    "schema_version", "job_id", "company", "title", "alignment_fingerprint",
    "response", "draft", "change_log", "unified_diff", "edit_budget", "g1",
}


def _parse_s3_bundle_structural(raw: object, path: str) -> S3Bundle:
    obj = _object(raw, _S3_BUNDLE_KEYS, path)
    job_id = obj["job_id"]
    if isinstance(job_id, bool) or not isinstance(job_id, int):
        raise G2ParseError(f"{path}.job_id: expected integer")
    fingerprint = obj["alignment_fingerprint"]
    if not isinstance(fingerprint, str) or len(fingerprint) != 64:
        raise G2ParseError(f"{path}.alignment_fingerprint: invalid fingerprint")
    response = _parse_s3_response_structural(obj["response"], f"{path}.response")
    draft = parse_tailored_draft(obj["draft"], f"{path}.draft")
    change_log = parse_change_log(obj["change_log"], f"{path}.change_log")
    unified_diff = obj["unified_diff"]
    if not isinstance(unified_diff, str):
        raise G2ParseError(f"{path}.unified_diff: expected string")
    edit_budget = parse_edit_budget(obj["edit_budget"], f"{path}.edit_budget")
    g1 = parse_g1_report(obj["g1"], f"{path}.g1")
    return S3Bundle(
        _string(obj["schema_version"], f"{path}.schema_version"),
        job_id,
        _string(obj["company"], f"{path}.company"),
        _string(obj["title"], f"{path}.title"),
        fingerprint,
        response,
        draft,
        change_log,
        unified_diff,
        edit_budget,
        g1,
    )


def _g2_round_to_dict(round_: G2Round) -> dict[str, object]:
    return {
        "round_index": round_.round_index,
        "response": g2_response_to_dict(round_.response),
        "verdict": round_.verdict.value,
        "trace_path": str(round_.trace_path) if round_.trace_path is not None else None,
    }


_G2_ROUND_KEYS = {"round_index", "response", "verdict", "trace_path"}
_G2_RESPONSE_KEYS = {"scores", "findings"}


def _parse_g2_response_structural(raw: object, path: str) -> G2Response:
    obj = _object(raw, _G2_RESPONSE_KEYS, path)
    scores = _parse_scores(obj["scores"], f"{path}.scores")
    findings = _parse_finding_list(obj["findings"], f"{path}.findings")
    return G2Response(scores, findings)


def _parse_g2_round(raw: object, path: str) -> G2Round:
    obj = _object(raw, _G2_ROUND_KEYS, path)
    round_index = obj["round_index"]
    if isinstance(round_index, bool) or not isinstance(round_index, int):
        raise G2ParseError(f"{path}.round_index: expected integer")
    response = _parse_g2_response_structural(obj["response"], f"{path}.response")
    verdict = G2Verdict(obj["verdict"])
    trace_path_raw = obj["trace_path"]
    if trace_path_raw is not None and not isinstance(trace_path_raw, str):
        raise G2ParseError(f"{path}.trace_path: expected string or null")
    trace_path = Path(trace_path_raw) if trace_path_raw is not None else None
    return G2Round(round_index, response, verdict, trace_path)


_G2_BUNDLE_KEYS = {
    "schema_version", "job_id", "company", "title", "alignment_fingerprint",
    "accepted_s3_bundle", "rounds", "verdict", "open_findings", "rounds_used", "model_calls",
}


def g2_bundle_to_dict(bundle: G2Bundle) -> dict[str, object]:
    return {
        "schema_version": bundle.schema_version,
        "job_id": bundle.job_id,
        "company": bundle.company,
        "title": bundle.title,
        "alignment_fingerprint": bundle.alignment_fingerprint,
        "accepted_s3_bundle": _s3_bundle_to_dict(bundle.accepted_s3_bundle),
        "rounds": [_g2_round_to_dict(item) for item in bundle.rounds],
        "verdict": bundle.verdict.value,
        "open_findings": [_finding_to_dict(item) for item in bundle.open_findings],
        "rounds_used": bundle.rounds_used,
        "model_calls": bundle.model_calls,
    }


def parse_g2_bundle(raw: object) -> G2Bundle:
    obj = _object(raw, _G2_BUNDLE_KEYS, "$")
    if obj["schema_version"] != _G2_BUNDLE_SCHEMA_VERSION:
        raise G2ParseError(f"$.schema_version: expected {_G2_BUNDLE_SCHEMA_VERSION!r}")
    job_id = obj["job_id"]
    if isinstance(job_id, bool) or not isinstance(job_id, int):
        raise G2ParseError("$.job_id: expected integer")
    fingerprint = obj["alignment_fingerprint"]
    if not isinstance(fingerprint, str) or len(fingerprint) != 64:
        raise G2ParseError("$.alignment_fingerprint: invalid fingerprint")
    accepted_s3_bundle = _parse_s3_bundle_structural(obj["accepted_s3_bundle"], "$.accepted_s3_bundle")
    if not isinstance(obj["rounds"], list):
        raise G2ParseError("$.rounds: expected array")
    rounds = tuple(_parse_g2_round(item, f"$.rounds[{index}]") for index, item in enumerate(obj["rounds"]))
    verdict = G2Verdict(obj["verdict"])
    open_findings = _parse_finding_list(obj["open_findings"], "$.open_findings")
    rounds_used = obj["rounds_used"]
    if isinstance(rounds_used, bool) or not isinstance(rounds_used, int):
        raise G2ParseError("$.rounds_used: expected integer")
    model_calls = obj["model_calls"]
    if isinstance(model_calls, bool) or not isinstance(model_calls, int):
        raise G2ParseError("$.model_calls: expected integer")
    return G2Bundle(
        obj["schema_version"], job_id, _string(obj["company"], "$.company"), _string(obj["title"], "$.title"),
        fingerprint, accepted_s3_bundle, rounds, verdict, open_findings, rounds_used, model_calls,
    )
