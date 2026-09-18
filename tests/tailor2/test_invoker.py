"""Unit tests for Tailor2 model invoker and safety boundaries."""

import pytest
from pathlib import Path

from src.tailor2.invoker import Tailor2Invoker


def test_invoker_requires_explicit_model_for_live_runs():
    # Omitting model must raise ValueError
    with pytest.raises(ValueError, match="Explicit --model name is required"):
        Tailor2Invoker(provider="openai", model=None)

    with pytest.raises(ValueError, match="Explicit --model name is required"):
        Tailor2Invoker(provider="claude", model="")


def test_invoker_unknown_provider_raises():
    with pytest.raises(ValueError, match="unknown provider"):
        Tailor2Invoker(provider="unknown_provider", model="some-model")


def test_invoker_fake_responses_used_in_tests(tmp_path):
    invoker = Tailor2Invoker(
        provider="openai",
        model="gpt-4o",
        fake_responses={
            "draft": '{"status": "ok"}',
            "audit": '{"overall_verdict": "PASS"}',
        },
        trace_dir=tmp_path / "traces",
    )

    draft_out = invoker.invoke("Draft prompt", invocation_type="draft")
    assert draft_out == '{"status": "ok"}'

    audit_out = invoker.invoke("Audit prompt", invocation_type="audit")
    assert audit_out == '{"overall_verdict": "PASS"}'

    # Verify trace is written
    traces = list((tmp_path / "traces").rglob("*.json"))
    assert len(traces) == 2
