import json
from pathlib import Path
from unittest.mock import patch

from scripts import scoring_stress

FIXTURES = Path(__file__).parent / "fixtures" / "scoring_stress"


def test_load_cases_reads_ten_synthetic_jds():
    cases = scoring_stress.load_cases(FIXTURES / "cases.json")
    assert len(cases) == 10
    assert {c["category"] for c in cases} == {
        "perfect_backend_match",
        "perfect_llm_agent_match",
        "strong_overlap_minor_gap",
        "partial_overlap_adjacent_stack",
        "partial_overlap_ml_stretch",
        "wrong_specialty",
        "hard_requirement_miss_years",
        "no_sponsorship_scorer_blind",
        "keyword_stuffed",
        "stale_vague",
    }
    for case in cases:
        assert len(case["expected_band"]) == 2
        assert case["expected_band"][0] <= case["expected_band"][1]


def test_every_band_is_provisional_until_a_clean_labelled_round_exists():
    """M6.13R: the 2026-07-19 CALIBRATED flip cited 36 human fit labels across
    three clean rounds. That evidence was retracted (only one clean round
    survives), so no band may claim CALIBRATED until Phase 2 re-closes."""
    cases = scoring_stress.load_cases(FIXTURES / "cases.json")

    assert {case["band_status"] for case in cases} == {"PROVISIONAL"}


def test_sponsorship_case_is_not_presented_as_a_scorer_safety_test():
    """Rejecting an explicitly no-sponsorship posting is the deterministic
    eligibility gate's job (tests/test_eligibility.py), never the scorer's.
    This case must not read as a scorer-side sponsorship cap."""
    cases = scoring_stress.load_cases(FIXTURES / "cases.json")
    (case,) = [c for c in cases if "sponsor" in c["category"]]

    assert case["category"] == "no_sponsorship_scorer_blind"
    assert "NOT a sponsorship safety test" in case["note"]
    assert "eligibility" in case["note"]


def test_build_batch_reshapes_cases_into_schema_v2_objects():
    cases = scoring_stress.load_cases(FIXTURES / "cases.json")
    batch = scoring_stress.build_batch(cases)
    assert len(batch) == 10
    for obj in batch:
        assert set(obj.keys()) == {"id", "row_ids", "company", "title", "locations", "flags", "jd_quality", "jd_text"}
        assert obj["row_ids"] == [obj["id"]]


def test_check_adherence_flags_in_band_and_out_of_band():
    cases = [
        {"id": 1, "category": "a", "expected_band": [8, 10]},
        {"id": 2, "category": "b", "expected_band": [0, 4]},
    ]
    scored = [
        {"id": 1, "fit_score": 9.0, "rationale": "great"},
        {"id": 2, "fit_score": 7.0, "rationale": "bad"},  # out of band
    ]

    report = scoring_stress.check_adherence(cases, scored)

    assert report[0]["in_band"] is True
    assert report[1]["in_band"] is False


def test_check_adherence_handles_missing_scored_entry():
    cases = [{"id": 1, "category": "a", "expected_band": [8, 10]}]
    report = scoring_stress.check_adherence(cases, scored=[])
    assert report[0]["in_band"] is False
    assert report[0]["actual"] is None


def test_main_reports_pass_when_all_scores_in_band(tmp_path):
    cases = scoring_stress.load_cases(FIXTURES / "cases.json")
    fake_scored = [
        {
            "id": case["id"],
            "row_ids": [case["id"]],
            "fit_score": sum(case["expected_band"]) / 2,
            "base_variant": "backend",
            "missing_keywords": [],
            "rationale": "synthetic",
        }
        for case in cases
    ]

    def fake_score_batch(batch_path, **kwargs):
        out_path = Path(str(batch_path).replace(".json", ".scored.json"))
        out_path.write_text(json.dumps(fake_scored))
        return out_path

    with patch.object(scoring_stress.score_batch, "score_batch", side_effect=fake_score_batch):
        exit_code = scoring_stress.main(["--out-dir", str(tmp_path), "--cases", str(FIXTURES / "cases.json")])

    assert exit_code == 0


def test_main_reports_failure_when_a_score_is_out_of_band(tmp_path):
    cases = scoring_stress.load_cases(FIXTURES / "cases.json")
    fake_scored = [
        {
            "id": case["id"],
            "row_ids": [case["id"]],
            "fit_score": 0.0,  # deliberately wrong for every case
            "base_variant": "backend",
            "missing_keywords": [],
            "rationale": "synthetic",
        }
        for case in cases
    ]

    def fake_score_batch(batch_path, **kwargs):
        out_path = Path(str(batch_path).replace(".json", ".scored.json"))
        out_path.write_text(json.dumps(fake_scored))
        return out_path

    with patch.object(scoring_stress.score_batch, "score_batch", side_effect=fake_score_batch):
        exit_code = scoring_stress.main(["--out-dir", str(tmp_path), "--cases", str(FIXTURES / "cases.json")])

    assert exit_code == 1
