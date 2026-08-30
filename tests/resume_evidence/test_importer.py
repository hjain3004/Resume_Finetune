from __future__ import annotations

import copy
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from src.resume_evidence.importer import import_corpus, validate_corpus
from src.resume_evidence.model import EditorialDimension
from src.resume_evidence.policy import AdmissionStatus
from src.resume_evidence.serde import EvidenceValidationError


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _ratings() -> list[dict[str, object]]:
    return [
        {
            "dimension": dimension.value,
            "score": 2,
            "explanation": f"Synthetic assessment for {dimension.value}.",
        }
        for dimension in EditorialDimension
    ]


def _source(source_id: str, url: str, snapshot_file: str, text: str) -> dict[str, object]:
    return {
        "source_id": source_id,
        "url": url,
        "title": f"Synthetic {source_id}",
        "retrieved_at": "2026-08-29T12:00:00Z",
        "content_sha256": _sha(text),
        "snapshot_file": snapshot_file,
    }


def _write_outcome(root: Path, reference_id: str, *, token: str, months: int = 7) -> None:
    bundle = root / "outcomes" / reference_id
    (bundle / "sources").mkdir(parents=True)
    resume = (
        "# Experience\nBuilt a deterministic queue processor with retries and metrics "
        f"for synthetic workload {token}.\n# Projects\nDesigned a cache simulator {token}.\n"
    )
    outcome = "The candidate reached a recruiter screen for the synthetic platform role.\n"
    (bundle / "sources" / "resume.md").write_text(resume, encoding="utf-8")
    (bundle / "sources" / "outcome.md").write_text(outcome, encoding="utf-8")
    end = "2026-01" if months == 7 else "2028-08"
    payload = {
        "schema_version": "m8q.resume_evidence.v1",
        "reference_id": reference_id,
        "source_kind": "huntr",
        "sources": [
            _source(
                "resume",
                f"https://huntr.co/resume/{reference_id}",
                "sources/resume.md",
                resume,
            ),
            _source(
                "outcome",
                f"https://huntr.co/outcome/{reference_id}",
                "sources/outcome.md",
                outcome,
            ),
        ],
        "resume_source_id": "resume",
        "outcome_source_id": "outcome",
        "layout_file": None,
        "layout_sha256": None,
        "role_family": "backend_platform",
        "target_role": "Backend Engineer",
        "target_level": "New Grad",
        "graduation_month": "2025-05",
        "professional_intervals": [{"start_month": "2025-06", "end_month": end}],
        "internship_intervals": [],
        "professional_experience_months": months,
        "experience_confidence": "derived",
        "outcome_tier": "recruiter_screen",
        "outcome_evidence_quote": "reached a recruiter screen for the synthetic platform role",
        "outcome_evidence_confidence": "publisher_asserted",
        "resume_representation": "anonymized",
        "resume_version_attribution": "publisher_linked",
        "section_order": ["experience", "projects"],
        "feature_tags": ["synthetic"],
        "editorial_ratings": _ratings(),
        "limitations": ["Synthetic fixture only."],
    }
    (bundle / "bundle.yaml").write_text(
        yaml.safe_dump(payload, sort_keys=False), encoding="utf-8"
    )


def _write_doctrine(root: Path, doctrine_id: str = "doc_a") -> None:
    record = root / "doctrine" / doctrine_id
    (record / "sources").mkdir(parents=True)
    text = "Use concrete technical detail when the supporting evidence is available.\n"
    (record / "sources" / "source.md").write_text(text, encoding="utf-8")
    payload = {
        "schema_version": "m8q.resume_evidence.v1",
        "doctrine_id": doctrine_id,
        "source": _source(
            "doctrine", "https://example.test/doctrine", "sources/source.md", text
        ),
        "authority_kind": "practitioner_first_party",
        "principle": "Use concrete technical detail.",
        "early_career_applicability": "Applies to project and internship evidence.",
        "affected_dimensions": ["technical_specificity"],
        "supporting_quote": "Use concrete technical detail when the supporting evidence is available",
        "conflicts_or_qualifications": ["Only when supported."],
        "confidence": "medium",
        "permitted_uses": ["pattern_context"],
    }
    (record / "record.yaml").write_text(
        yaml.safe_dump(payload, sort_keys=False), encoding="utf-8"
    )


def _write_pattern(root: Path, pattern_id: str = "pattern_a") -> None:
    record = root / "patterns" / pattern_id
    record.mkdir(parents=True)
    payload = {
        "schema_version": "m8q.resume_evidence.v1",
        "pattern_id": pattern_id,
        "text": "Use concrete technical detail when evidence supports it.",
        "anti_pattern": False,
        "role_families": ["backend_platform"],
        "outcome_record_ids": ["outcome_a"],
        "doctrine_record_ids": ["doc_a"],
        "limitations": ["Synthetic basis."],
        "confidence": "low",
        "prohibited_uses": ["automatic_copying"],
        "candidate_dimensions": ["technical_specificity"],
    }
    (record / "record.yaml").write_text(
        yaml.safe_dump(payload, sort_keys=False), encoding="utf-8"
    )


def _write_manifest(root: Path, payload: dict[str, object]) -> Path:
    path = root / "manifest.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def _base_corpus(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "inbox"
    _write_outcome(root, "outcome_a", token="alpha")
    _write_outcome(root, "outcome_b", token="beta", months=38)
    _write_doctrine(root)
    _write_pattern(root)
    manifest = _write_manifest(
        root,
        {
            "schema_version": "m8q.resume_evidence.v1",
            "corpus_version": "0.1.0",
            "promote_outcome_ids": ["outcome_a"],
            "excluded_outcomes": [
                {"reference_id": "outcome_b", "reason": "Over experience limit."}
            ],
            "expected_doctrine_ids": ["doc_a"],
            "expected_pattern_ids": ["pattern_a"],
        },
    )
    return root, manifest


def test_valid_corpus_is_sorted_and_preserves_explicit_dispositions(tmp_path):
    root, manifest = _base_corpus(tmp_path)
    validated = validate_corpus(root, manifest)
    assert [item.reference_id for item in validated.outcomes] == ["outcome_a", "outcome_b"]
    assert [item.reference_id for item in validated.decisions] == ["outcome_a", "outcome_b"]
    assert validated.decisions[0].admission.status is AdmissionStatus.ACCEPTED
    assert validated.decisions[0].disposition == "promote"
    assert validated.decisions[1].admission.status is AdmissionStatus.REJECTED
    assert validated.decisions[1].exclusion_reason == "Over experience limit."


@pytest.mark.parametrize(
    "mutation",
    [
        lambda data: data.update(promote_outcome_ids=[]),
        lambda data: data.update(expected_doctrine_ids=[]),
        lambda data: data.update(expected_pattern_ids=[]),
        lambda data: data.update(unexpected="value"),
    ],
)
def test_manifest_missing_unexpected_or_unclassified_records_fail(tmp_path, mutation):
    root, manifest = _base_corpus(tmp_path)
    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    mutation(data)
    manifest.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    with pytest.raises(EvidenceValidationError):
        validate_corpus(root, manifest)


def test_excluded_outcome_requires_nonempty_reason(tmp_path):
    root, manifest = _base_corpus(tmp_path)
    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    data["excluded_outcomes"][0]["reason"] = "  "
    manifest.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    with pytest.raises(EvidenceValidationError):
        validate_corpus(root, manifest)


def test_same_outcome_cannot_be_promoted_and_excluded(tmp_path):
    root, manifest = _base_corpus(tmp_path)
    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    data["excluded_outcomes"].append({"reference_id": "outcome_a", "reason": "Conflict."})
    manifest.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    with pytest.raises(EvidenceValidationError):
        validate_corpus(root, manifest)


def test_nonaccepted_promoted_outcome_fails(tmp_path):
    root, manifest = _base_corpus(tmp_path)
    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    data["promote_outcome_ids"] = ["outcome_b"]
    data["excluded_outcomes"] = [{"reference_id": "outcome_a", "reason": "Not selected."}]
    manifest.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    pattern = root / "patterns" / "pattern_a" / "record.yaml"
    pattern_payload = yaml.safe_load(pattern.read_text(encoding="utf-8"))
    pattern_payload["outcome_record_ids"] = ["outcome_b"]
    pattern.write_text(yaml.safe_dump(pattern_payload, sort_keys=False), encoding="utf-8")
    with pytest.raises(EvidenceValidationError, match="accepted"):
        validate_corpus(root, manifest)


def test_structurally_corrupt_excluded_outcome_still_fails(tmp_path):
    root, manifest = _base_corpus(tmp_path)
    bundle = root / "outcomes" / "outcome_b" / "bundle.yaml"
    payload = yaml.safe_load(bundle.read_text(encoding="utf-8"))
    payload["unexpected"] = True
    bundle.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    with pytest.raises(EvidenceValidationError):
        validate_corpus(root, manifest)


def test_directory_and_record_id_must_agree(tmp_path):
    root, manifest = _base_corpus(tmp_path)
    bundle = root / "outcomes" / "outcome_a" / "bundle.yaml"
    payload = yaml.safe_load(bundle.read_text(encoding="utf-8"))
    payload["reference_id"] = "different_id"
    bundle.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    with pytest.raises(EvidenceValidationError, match="directory"):
        validate_corpus(root, manifest)


def test_unexpected_nonhidden_file_fails(tmp_path):
    root, manifest = _base_corpus(tmp_path)
    (root / "notes.txt").write_text("unexpected", encoding="utf-8")
    with pytest.raises(EvidenceValidationError, match="unexpected"):
        validate_corpus(root, manifest)


def test_pattern_may_reference_only_promoted_outcomes(tmp_path):
    root, manifest = _base_corpus(tmp_path)
    pattern = root / "patterns" / "pattern_a" / "record.yaml"
    payload = yaml.safe_load(pattern.read_text(encoding="utf-8"))
    payload["outcome_record_ids"] = ["outcome_b"]
    pattern.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    with pytest.raises(EvidenceValidationError, match="unknown outcome"):
        validate_corpus(root, manifest)


def test_duplicate_promoted_outcomes_block_corpus(tmp_path):
    root, manifest = _base_corpus(tmp_path)
    second = root / "outcomes" / "outcome_b" / "bundle.yaml"
    payload = yaml.safe_load(second.read_text(encoding="utf-8"))
    first = yaml.safe_load(
        (root / "outcomes" / "outcome_a" / "bundle.yaml").read_text(encoding="utf-8")
    )
    payload["sources"][0]["url"] = first["sources"][0]["url"]
    payload["professional_intervals"] = [
        {"start_month": "2025-06", "end_month": "2026-01"}
    ]
    payload["professional_experience_months"] = 7
    second.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    data["promote_outcome_ids"] = ["outcome_a", "outcome_b"]
    data["excluded_outcomes"] = []
    manifest.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    with pytest.raises(EvidenceValidationError, match="duplicate"):
        validate_corpus(root, manifest)


def test_unsupported_schema_version_fails(tmp_path):
    root, manifest = _base_corpus(tmp_path)
    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    data["schema_version"] = "m8q.resume_evidence.v999"
    manifest.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    with pytest.raises(EvidenceValidationError, match="schema_version"):
        validate_corpus(root, manifest)


def test_import_is_bound_to_exact_approved_report_hash(tmp_path):
    root, manifest = _base_corpus(tmp_path)
    bank_root = tmp_path / "bank"
    with pytest.raises(EvidenceValidationError, match="approval"):
        import_corpus(
            root,
            manifest,
            bank_root,
            approved_report_sha256="0" * 64,
            approved_at=datetime(2026, 8, 30, tzinfo=timezone.utc),
        )
    assert not bank_root.exists()
