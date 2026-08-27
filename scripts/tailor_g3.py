"""Fail-closed G3 review packet + feedback CLI.

`build` consumes already-accepted upstream artifacts -- an S3 bundle, a G2
bundle, a render result, and the S1/S0/S2 response files -- and derives a
review packet from them. It does not re-run S1->S2->S3 chain validation a
second time: the G2 bundle's own embedded `accepted_s3_bundle` was already
produced by the authoritative, three-argument `parse_s3_bundle` at G2-accept
time (scripts/tailor_g2.py invoke), so `build` treats that embedded bundle
as the trusted S3Bundle and cross-checks the separately-supplied --bundle
file against it byte-for-byte rather than re-deriving the whole upstream
chain from the database a second time. G3's own design principle is that
the packet "invents nothing" and is a deterministic projection of
already-validated fields -- consistent with not re-validating what an
earlier, already-fail-closed CLI already validated.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.render.emphasis import parse_emphasis
from src.tailor.feedback import (
    DEFAULT_FEEDBACK_DIR,
    FeedbackOutcomeKind,
    parse_feedback_form,
    store_feedback,
    summarize_feedback,
)
from src.tailor.g2_pipeline import parse_g2_bundle
from src.tailor.g3 import G3OutcomeKind, build_review_packet, parse_packet, publish_packet
from src.tailor.publish import parse_render_result
from src.tailor.s3_pipeline import s3_bundle_to_dict


def _read(path: Path) -> object:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _fail(label: str, exc: Exception) -> int:
    print(f"tailor_g3 {label}: {exc}", file=sys.stderr)
    return 1


def _load_s1_for_packet(raw: dict):
    from src.tailor.s1 import InjectionFlag, Requirement, S1Response

    return S1Response(
        must_have=tuple(Requirement(term=item["term"], quote=item["quote"]) for item in raw["must_have"]),
        nice_to_have=(), responsibilities_summary=(), seniority_signals=(), disqualifiers=(),
        company_context=None,
        suspected_injection=tuple(
            InjectionFlag(quote=item["quote"], reason=item["reason"]) for item in raw.get("suspected_injection", [])
        ),
    )


def _load_s0_for_packet(raw: dict):
    from src.tailor.s0 import PositioningPoint, S0Response

    return S0Response(
        context_mode=raw.get("context_mode", "jd_only"),
        points=tuple(
            PositioningPoint(
                sentence=point["sentence"], profile_ids=tuple(point.get("profile_ids", ())),
                requirement_terms=tuple(point.get("requirement_terms", ())),
                jd_quotes=tuple(point.get("jd_quotes", ())),
            )
            for point in raw["points"]
        ),
    )


def _load_s2_for_packet(raw: dict):
    from src.tailor.s2 import CoverageEntry, ProjectChoice, S2Response

    return S2Response(
        base_variant=raw["base_variant"],
        projects=tuple(
            ProjectChoice(project_id=item["project_id"], reason=item["reason"],
                         s0_point_indexes=tuple(item.get("s0_point_indexes", ())))
            for item in raw["projects"]
        ),
        bullet_order=tuple(raw["bullet_order"]),
        coverage=tuple(
            CoverageEntry(term=item["term"], status=item["status"], bullet_ids=tuple(item.get("bullet_ids", ())))
            for item in raw["coverage"]
        ),
    )


def cmd_build(args) -> int:
    try:
        g2_bundle = parse_g2_bundle(_read(Path(args.g2_bundle)))
        s3_bundle = g2_bundle.accepted_s3_bundle

        raw_bundle_file = _read(Path(args.bundle))
        if raw_bundle_file != s3_bundle_to_dict(s3_bundle):
            raise ValueError(
                "--bundle does not match the accepted S3 bundle embedded in --g2-bundle"
            )

        render_result = parse_render_result(_read(Path(args.render_result)))
        s1 = _load_s1_for_packet(_read(Path(args.s1)))
        s0 = _load_s0_for_packet(_read(Path(args.s0)))
        s2 = _load_s2_for_packet(_read(Path(args.s2)))

        packet = build_review_packet(s3_bundle, g2_bundle, render_result, s1, s0, s2)
        changed_bullet_ids = tuple(edit.bullet_id for edit in s3_bundle.response.bullet_edits)
        outcome = publish_packet(packet, changed_bullet_ids, Path(args.output))
        if outcome.kind not in (G3OutcomeKind.BUILT, G3OutcomeKind.ALREADY_BUILT):
            return _fail("build", ValueError(f"{outcome.kind.value}: {outcome.error}"))

        print(f"G3 packet {outcome.kind.value} for job {s3_bundle.job_id} ({s3_bundle.company} — {s3_bundle.title})")
        return 0
    except Exception as exc:
        return _fail("build", exc)


def cmd_record(args) -> int:
    try:
        packet = parse_packet(_read(Path(args.packet)))
        form_text = Path(args.form).read_text(encoding="utf-8")

        changed_bullet_ids = frozenset(
            location.split(":", 1)[1] for location, *_ in packet.changes if location.startswith("bullet:")
        )
        bullet_plain_text_by_id = {
            location.split(":", 1)[1]: parse_emphasis(after)[0]
            for location, before, after, quote, rule in packet.changes if location.startswith("bullet:")
        }

        record = parse_feedback_form(
            form_text, job_id=packet.job_id, alignment_fingerprint=packet.alignment_fingerprint,
            changed_bullet_ids=changed_bullet_ids, bullet_plain_text_by_id=bullet_plain_text_by_id,
        )
        feedback_dir = Path(args.feedback_dir) if args.feedback_dir else DEFAULT_FEEDBACK_DIR
        outcome = store_feedback(record, feedback_dir=feedback_dir)
        if outcome.kind not in (FeedbackOutcomeKind.RECORDED, FeedbackOutcomeKind.ALREADY_RECORDED):
            return _fail("record", ValueError(f"{outcome.kind.value}: {outcome.error}"))

        print(f"feedback {outcome.kind.value}: revision {outcome.revision} at {outcome.path}")
        return 0
    except Exception as exc:
        return _fail("record", exc)


def cmd_summarize(args) -> int:
    try:
        feedback_dir = Path(args.feedback_dir) if args.feedback_dir else DEFAULT_FEEDBACK_DIR
        summary = summarize_feedback(feedback_dir, job_id=args.job_id)
        print(f"total: {summary.total}")
        print(f"accepted: {summary.accepted}")
        print(f"rejected: {summary.rejected}")
        print(f"would_submit_yes: {summary.would_submit_yes}")
        print(f"would_submit_no: {summary.would_submit_no}")
        print(f"would_submit_not_as_is: {summary.would_submit_not_as_is}")
        print(f"needs_revision: {summary.needs_revision}")
        print(f"mean_company_alignment: {summary.mean_company_alignment:.2f}")
        print(f"mean_visual_quality: {summary.mean_visual_quality:.2f}")
        print(f"distinct_jobs: {summary.distinct_jobs}")
        return 0
    except Exception as exc:
        return _fail("summarize", exc)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scripts.tailor_g3")
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build")
    build.add_argument("--bundle", required=True)
    build.add_argument("--g2-bundle", required=True)
    build.add_argument("--render-result", required=True)
    build.add_argument("--s1", required=True)
    build.add_argument("--s0", required=True)
    build.add_argument("--s2", required=True)
    build.add_argument("--output", required=True)
    build.set_defaults(func=cmd_build)

    record = sub.add_parser("record")
    record.add_argument("--form", required=True)
    record.add_argument("--packet", required=True)
    record.add_argument("--feedback-dir")
    record.set_defaults(func=cmd_record)

    summarize = sub.add_parser("summarize")
    summarize.add_argument("--feedback-dir")
    summarize.add_argument("--job-id", type=int, default=None)
    summarize.set_defaults(func=cmd_summarize)

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
