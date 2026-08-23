"""One-job offline preparation and invocation workflow for M8P-2."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from src import db
from src.profile import load_profile
from src.tailor.artifacts import write_json_atomic
from src.tailor.s1 import S1ParseError, parse_s1_request, parse_s1_response_dict, s1_response_to_dict
from src.tailor.s0 import S0ParseError, S0SemanticError, build_s0_request, parse_s0_request, parse_s0_response, s0_request_to_dict, s0_response_to_dict
from src.tailor.s0_pipeline import S0OutcomeKind, run_s0_invocation
from src.tailor.profile_views import positioning_to_dict, selection_to_dict, parse_selection
from src.tailor.s2 import S2ParseError, build_s2_request, parse_s2_request, parse_s2_response, s2_request_to_dict, s2_response_to_dict
from src.tailor.s2_pipeline import S2OutcomeKind, run_s2_invocation

S0_PROMPT = Path("docs/prompts/tailoring_s0.md"); S2_PROMPT = Path("docs/prompts/tailoring_s2.md"); TRACE_DIR = Path("data/traces")
def _read(path: Path): return json.loads(path.read_text())
def _fail(label: str, exc: Exception) -> int: print(f"tailor_s0_s2 {label}: {exc}", file=sys.stderr); return 1

def cmd_prepare(a):
    try:
        conn = db.get_readonly_connection(a.db); request = db.prepare_tailoring_request(conn, a.job_id); variant = db.tailoring_base_variant(conn, a.job_id); conn.close()
        persisted = parse_s1_request(_read(Path(a.s1_request)))
        if persisted != request: raise ValueError("persisted S1 request does not match eligible DB row")
        response = parse_s1_response_dict(_read(Path(a.s1)), request.jd_text)
        profile = load_profile(a.profile); positioning = profile.for_positioning(); catalog = profile.for_selection(variant)
        s0request = build_s0_request(request.job_id, request.company, request.title, response, positioning)
        out = Path(a.output); write_json_atomic(out / "s0_request.json", s0_request_to_dict(s0request)); write_json_atomic(out / "s2_catalog.json", selection_to_dict(catalog))
        print(f"Wrote preparation artifacts for job {request.job_id} ({len(json.dumps(s0_request_to_dict(s0request)))} request chars)"); return 0
    except Exception as exc: return _fail("prepare", exc)

def cmd_invoke_s0(a):
    try:
        request_path = Path(a.request); request = parse_s0_request(_read(request_path)); prompt = S0_PROMPT if a.prompt_template is None else Path(a.prompt_template); built = __import__('src.tailor.s0', fromlist=['build_s0_prompt']).build_s0_prompt(prompt.read_text(), request)
        if a.dry_run: print(f"[dry-run] S0 prompt validated ({len(built)} chars); no model call, trace, or s0.json."); return 0
        outcome = run_s0_invocation(request, prompt_template_path=prompt, request_path=request_path, timeout=a.timeout, trace_dir=Path(a.trace_dir) if a.trace_dir else TRACE_DIR)
        if outcome.kind != S0OutcomeKind.VALID: return _fail("invoke-s0", ValueError(f"{outcome.kind.value}: {outcome.error}"))
        write_json_atomic(Path(a.output) / "s0.json", s0_response_to_dict(outcome.response)); print(f"Wrote {Path(a.output) / 's0.json'} for job {request.job_id}"); return 0
    except Exception as exc: return _fail("invoke-s0", exc)

def cmd_prepare_s2(a):
    try:
        s1req = parse_s1_request(_read(Path(a.s1_request))); raw_s0req = parse_s0_request(_read(Path(a.s0_request))); s1_raw = _read(Path(a.s1)); s1 = parse_s1_response_dict(s1_raw, s1req.jd_text); catalog = parse_selection(_read(Path(a.catalog)))
        if raw_s0req.job_id != s1req.job_id or raw_s0req.company != s1req.company or raw_s0req.title != s1req.title: raise ValueError("S0 request and S1 request identity mismatch")
        if s1_response_to_dict(raw_s0req.s1) != s1_response_to_dict(s1): raise ValueError("persisted S1 differs between S0 request and S1 artifact")
        validated_s0_request = build_s0_request(s1req.job_id, s1req.company, s1req.title, s1, raw_s0req.positioning)
        raw_s0 = parse_s0_response(json.dumps(_read(Path(a.s0))), validated_s0_request)
        request = build_s2_request(s1req.job_id, s1req.company, s1req.title, s1, raw_s0, catalog); write_json_atomic(Path(a.output) / "s2_request.json", s2_request_to_dict(request)); print(f"Wrote {Path(a.output) / 's2_request.json'} for job {request.job_id}"); return 0
    except Exception as exc: return _fail("prepare-s2", exc)

def cmd_invoke_s2(a):
    try:
        request_path = Path(a.request); request = parse_s2_request(_read(request_path)); prompt = S2_PROMPT if a.prompt_template is None else Path(a.prompt_template); built = __import__('src.tailor.s2', fromlist=['build_s2_prompt']).build_s2_prompt(prompt.read_text(), request)
        if a.dry_run: print(f"[dry-run] S2 prompt validated ({len(built)} chars); no model call, trace, or s2.json."); return 0
        outcome = run_s2_invocation(request, prompt_template_path=prompt, request_path=request_path, timeout=a.timeout, trace_dir=Path(a.trace_dir) if a.trace_dir else TRACE_DIR)
        if outcome.kind != S2OutcomeKind.VALID: return _fail("invoke-s2", ValueError(f"{outcome.kind.value}: {outcome.error}"))
        write_json_atomic(Path(a.output) / "s2.json", s2_response_to_dict(outcome.response)); print(f"Wrote {Path(a.output) / 's2.json'} for job {request.job_id}"); return 0
    except Exception as exc: return _fail("invoke-s2", exc)

def build_parser():
    p = argparse.ArgumentParser(prog="python -m scripts.tailor_s0_s2"); sub = p.add_subparsers(dest="command", required=True)
    x = sub.add_parser("prepare"); x.add_argument("--job-id", type=int, required=True); x.add_argument("--db", required=True); x.add_argument("--s1-request", required=True); x.add_argument("--s1", required=True); x.add_argument("--profile", required=True); x.add_argument("--output", required=True); x.set_defaults(func=cmd_prepare)
    x = sub.add_parser("invoke-s0"); x.add_argument("--request", required=True); x.add_argument("--output", required=True); x.add_argument("--prompt-template"); x.add_argument("--trace-dir"); x.add_argument("--timeout", type=float, default=300); x.add_argument("--dry-run", action="store_true"); x.set_defaults(func=cmd_invoke_s0)
    x = sub.add_parser("prepare-s2"); x.add_argument("--s1-request", required=True); x.add_argument("--s1", required=True); x.add_argument("--s0", required=True); x.add_argument("--s0-request", required=True); x.add_argument("--catalog", required=True); x.add_argument("--output", required=True); x.set_defaults(func=cmd_prepare_s2)
    x = sub.add_parser("invoke-s2"); x.add_argument("--request", required=True); x.add_argument("--output", required=True); x.add_argument("--prompt-template"); x.add_argument("--trace-dir"); x.add_argument("--timeout", type=float, default=300); x.add_argument("--dry-run", action="store_true"); x.set_defaults(func=cmd_invoke_s2)
    return p
def main(argv=None):
    return build_parser().parse_args(argv).func(build_parser().parse_args(argv)) if False else (lambda a: a.func(a))(build_parser().parse_args(argv))
if __name__ == "__main__": raise SystemExit(main())
