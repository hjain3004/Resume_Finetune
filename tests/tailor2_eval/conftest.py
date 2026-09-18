"""Shared fixtures for tests/tailor2_eval/."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.tailor2_eval.schemas import human_review_from_dict, target_result_from_dict

SCENARIOS_PATH = Path("tests/fixtures/tailor2_eval/scenarios.json")
VALID_PLAN_PATH = Path("tests/fixtures/tailor2_eval/plans/valid_plan.json")
INVALID_PLAN_MISSING_FIELD_PATH = Path("tests/fixtures/tailor2_eval/plans/invalid_plan_missing_field.json")
INVALID_PLAN_WITH_CREDENTIAL_PATH = Path("tests/fixtures/tailor2_eval/plans/invalid_plan_with_credential.json")


@pytest.fixture(scope="session")
def scenarios() -> dict:
    return json.loads(SCENARIOS_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def target_result_factory(scenarios):
    def _make(name: str):
        return target_result_from_dict(scenarios["target_results"][name])

    return _make


@pytest.fixture
def human_review_factory(scenarios):
    def _make(name: str):
        return human_review_from_dict(scenarios["human_reviews"][name])

    return _make


@pytest.fixture
def all_target_results(scenarios):
    return [target_result_from_dict(v) for v in scenarios["target_results"].values()]


@pytest.fixture
def all_human_reviews(scenarios):
    return [human_review_from_dict(v) for v in scenarios["human_reviews"].values()]
