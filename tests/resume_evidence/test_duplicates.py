from __future__ import annotations

import dataclasses

from src.resume_evidence.duplicates import (
    canonical_source_url,
    find_duplicates,
    resume_signature,
)


def test_tracking_parameters_do_not_create_distinct_sources(valid_candidate):
    left = valid_candidate
    right_source = dataclasses.replace(
        left.sources[0],
        url=left.sources[0].url + "?utm_source=newsletter&gclid=abc",
    )
    right = dataclasses.replace(
        left,
        reference_id="cand_synthetic_002",
        sources=(right_source, left.sources[1]),
    )

    pairs = find_duplicates(
        (left, right),
        {
            left.reference_id: "Experience\nBuilt a deterministic queue processor.",
            right.reference_id: "Projects\nDesigned an unrelated compiler frontend.",
        },
    )

    assert len(pairs) == 1
    assert pairs[0].kind == "source_url"


def test_content_affecting_query_values_are_preserved():
    first = canonical_source_url("https://EXAMPLE.test/resume?id=1&utm_source=x")
    second = canonical_source_url("https://example.test/resume?id=2&utm_source=y")
    assert first == "https://example.test/resume?id=1"
    assert second == "https://example.test/resume?id=2"
    assert first != second


def test_exact_resume_hash_duplicate_is_reported(valid_candidate):
    right = dataclasses.replace(
        valid_candidate,
        reference_id="cand_synthetic_002",
        sources=tuple(
            dataclasses.replace(
                source, url=source.url.replace("example.test", "different.test")
            )
            for source in valid_candidate.sources
        ),
    )
    pairs = find_duplicates(
        (valid_candidate, right),
        {
            valid_candidate.reference_id: "Experience\nBuilt service alpha.",
            right.reference_id: "Experience\nBuilt service beta.",
        },
    )
    assert len(pairs) == 1
    assert pairs[0].kind == "content_sha256"
    assert pairs[0].similarity == 1.0


def test_near_duplicate_above_point_nine_is_reported(valid_candidate):
    sources = tuple(
        dataclasses.replace(
            source,
            url=source.url.replace("src_", "different_"),
            content_sha256=("2" if index == 0 else "3") * 64,
        )
        for index, source in enumerate(valid_candidate.sources)
    )
    right = dataclasses.replace(
        valid_candidate, reference_id="cand_synthetic_002", sources=sources
    )
    base = " ".join(f"token{index}" for index in range(120))
    altered = base.replace("token60", "replacement60")
    pairs = find_duplicates(
        (valid_candidate, right),
        {valid_candidate.reference_id: base, right.reference_id: altered},
    )
    assert len(pairs) == 1
    assert pairs[0].kind == "near_signature"
    assert pairs[0].similarity >= 0.90


def test_distinct_resume_below_threshold_is_not_reported(valid_candidate):
    sources = tuple(
        dataclasses.replace(
            source,
            url=f"https://different.test/{source.source_id}",
            content_sha256=("4" if index == 0 else "5") * 64,
        )
        for index, source in enumerate(valid_candidate.sources)
    )
    right = dataclasses.replace(
        valid_candidate, reference_id="cand_synthetic_002", sources=sources
    )
    pairs = find_duplicates(
        (valid_candidate, right),
        {
            valid_candidate.reference_id: "python queue worker retries metrics database",
            right.reference_id: "java compiler parser syntax tree optimizer bytecode",
        },
    )
    assert pairs == ()


def test_resume_signature_removes_obvious_contact_tokens():
    first = resume_signature(
        "Synthetic Person\nfirst@example.test\nExperience\nBuilt queue retry metrics service"
    )
    second = resume_signature(
        "Different Person\nsecond@example.test\nExperience\nBuilt queue retry metrics service"
    )
    assert first == second
