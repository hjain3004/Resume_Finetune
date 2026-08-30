from __future__ import annotations

import dataclasses
import json

from src.resume_evidence.importer import validate_corpus
from src.resume_evidence.report import (
    build_report,
    render_report_markdown,
    report_sha256,
    report_to_dict,
)

from tests.resume_evidence.test_importer import _base_corpus


def test_report_contains_complete_disposition_and_metric_counts(tmp_path):
    root, manifest = _base_corpus(tmp_path)
    report = build_report(validate_corpus(root, manifest))
    payload = report_to_dict(report)

    assert payload["outcome_counts"] == {
        "accepted": 1,
        "needs_review": 0,
        "rejected": 1,
        "total": 2,
    }
    assert payload["disposition_counts"] == {"exclude": 1, "promote": 1}
    assert payload["canonical_counts"] == {"doctrine": 1, "outcomes": 1, "patterns": 1}
    assert payload["source_kind_counts"] == {"huntr": 2}
    assert payload["role_family_counts"] == {"backend_platform": 2}
    assert payload["outcome_tier_counts"] == {"recruiter_screen": 2}
    assert payload["evidence_confidence_counts"] == {"publisher_asserted": 2}
    assert payload["representation_counts"] == {"anonymized": 2}
    assert [row["reference_id"] for row in payload["outcomes"]] == [
        "outcome_a",
        "outcome_b",
    ]
    assert payload["outcomes"][1]["exclusion_reason"] == "Over experience limit."


def test_report_hash_and_markdown_are_order_independent(tmp_path):
    root, manifest = _base_corpus(tmp_path)
    first = validate_corpus(root, manifest)
    second = dataclasses.replace(
        first,
        outcomes=tuple(reversed(first.outcomes)),
        doctrine=tuple(reversed(first.doctrine)),
        patterns=tuple(reversed(first.patterns)),
        decisions=tuple(reversed(first.decisions)),
        duplicates=tuple(reversed(first.duplicates)),
    )

    assert report_sha256(build_report(first)) == report_sha256(build_report(second))
    assert render_report_markdown(build_report(first)) == render_report_markdown(
        build_report(second)
    )


def test_report_contains_no_snapshot_text_or_private_paths(tmp_path):
    root, manifest = _base_corpus(tmp_path)
    report = build_report(validate_corpus(root, manifest))
    rendered = json.dumps(report_to_dict(report)) + render_report_markdown(report)
    assert "queue processor with retries" not in rendered
    assert "sources/resume.md" not in rendered
    assert str(root) not in rendered


def test_markdown_contains_exact_hash_approval_command(tmp_path):
    root, manifest = _base_corpus(tmp_path)
    report = build_report(validate_corpus(root, manifest))
    digest = report_sha256(report)
    markdown = render_report_markdown(report)
    assert digest in markdown
    assert "--approved-report-sha256" in markdown
