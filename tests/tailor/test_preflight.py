"""Model-free tailoring preflight (M8V-1 Task 1). No model call, no network,
no SQLite -- every check here is deterministic and runs before the first
model call. Render checks are skipped when pdflatex is unavailable."""
import dataclasses
import shutil
from pathlib import Path

import pytest

from src.profile import Bullet, ClaimType, Phrasings, load_profile


@pytest.fixture(scope="module")
def real_profile():
    return load_profile("config/master_profile.yaml")


def _profile_with_dnc_in(real_profile, field: str):
    term = real_profile.do_not_claim[0]
    project = real_profile.projects[0]
    modified = dataclasses.replace(project, **{field: f"{getattr(project, field)} {term}"})
    projects = (modified,) + real_profile.projects[1:]
    return dataclasses.replace(real_profile, projects=projects)


@pytest.fixture
def tmp_profile_with_dnc_in_tech_line(real_profile):
    return _profile_with_dnc_in(real_profile, "tech_line")


@pytest.fixture
def tmp_profile_with_dnc_in_title(real_profile):
    return _profile_with_dnc_in(real_profile, "display_title")


@pytest.fixture
def tmp_prompt_dir_with_duplicate_marker(tmp_path):
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    (prompt_dir / "tailoring_s1.md").write_text(
        "Some prompt text.\n\n{{S1_REQUEST_JSON}}\n\nMore text repeating the "
        "marker.\n\n{{S1_REQUEST_JSON}}\n",
        encoding="utf-8",
    )
    return prompt_dir


@pytest.fixture
def tmp_prompt_dir_with_fence(tmp_path):
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    (prompt_dir / "tailoring_s1.md").write_text(
        "Some prompt text.\n```json\n{}\n```\n\n{{S1_REQUEST_JSON}}\n",
        encoding="utf-8",
    )
    return prompt_dir


@pytest.fixture
def tmp_prompt_dir_missing_marker(tmp_path):
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    (prompt_dir / "tailoring_s1.md").write_text("No marker here at all.\n", encoding="utf-8")
    return prompt_dir


from src.tailor.preflight import (  # noqa: E402
    PreflightFinding,
    PreflightReport,
    check_prompt_invariants,
    check_profile_do_not_claim,
    check_variants_render,
    run_preflight,
)


def test_do_not_claim_in_tech_line_is_found(tmp_profile_with_dnc_in_tech_line):
    findings = check_profile_do_not_claim(tmp_profile_with_dnc_in_tech_line)
    assert any(f.surface == "tech_line" for f in findings)


def test_do_not_claim_in_display_title_is_found(tmp_profile_with_dnc_in_title):
    findings = check_profile_do_not_claim(tmp_profile_with_dnc_in_title)
    assert any(f.surface == "display_title" for f in findings)


def test_clean_real_profile_passes(real_profile):
    assert check_profile_do_not_claim(real_profile) == ()


def test_duplicate_marker_is_found(tmp_prompt_dir_with_duplicate_marker):
    findings = check_prompt_invariants(tmp_prompt_dir_with_duplicate_marker)
    assert any("exactly once" in f.message for f in findings)


def test_missing_marker_is_found(tmp_prompt_dir_missing_marker):
    findings = check_prompt_invariants(tmp_prompt_dir_missing_marker)
    assert any("exactly once" in f.message for f in findings)


def test_fenced_prompt_is_found(tmp_prompt_dir_with_fence):
    findings = check_prompt_invariants(tmp_prompt_dir_with_fence)
    assert any("fence" in f.message for f in findings)


def test_real_prompts_have_exactly_the_two_known_shape_defects():
    """Empirically discovered while implementing this check (2026-08-27):
    the real tailoring_s1.md and tailoring_s0.md prompts each document a
    response shape that fails their OWN stage's structural parser --
    tailoring_s1.md's example reuses the identical placeholder term across
    must_have and nice_to_have (tripping the structural duplicate-term
    guard), and tailoring_s0.md's example shows only one `points` entry
    against the prompt's own "two to four" rule. Neither is one of the
    five already-fixed live failures; both are newly discovered by this
    check and are out of scope to fix in M8V-1 (see docs/DECISIONS.md).
    No fence or marker defect exists in any real prompt, and s2/s3/g2 have
    no shape defect."""
    findings = check_prompt_invariants(Path("docs/prompts"))
    surfaces_with_findings = {f.surface for f in findings}
    assert surfaces_with_findings == {"tailoring_s0.md", "tailoring_s1.md"}
    assert all("shape" in f.message.casefold() for f in findings)
    assert all("fence" not in f.message.casefold() for f in findings)
    assert all("exactly once" not in f.message for f in findings)


def test_preflight_makes_no_model_call():
    src = Path("src/tailor/preflight.py").read_text(encoding="utf-8")
    assert "src.tailor.invoke" not in src and "src.llm_trace" not in src


def test_skip_render_omits_the_render_check(tmp_path, real_profile):
    report = run_preflight(
        Path("config/master_profile.yaml"), Path("profile/template.tex"),
        Path("docs/prompts"), tmp_path, skip_render=True,
    )
    assert not any(f.check == "render_l7" for f in report.findings)


@pytest.fixture
def clean_prompt_dir(tmp_path):
    """A synthetic prompt directory with none of the two known real-repo
    shape defects, isolating the aggregation test from them."""
    prompt_dir = tmp_path / "clean_prompts"
    prompt_dir.mkdir()
    (prompt_dir / "tailoring_g2.md").write_text(
        "Return exactly one JSON object.\n\n"
        '{\n  "scores": {"C1": 3, "C2": 3, "C3": 3, "C4": 3, "C5": 3},\n  "findings": []\n}\n'
        "\n{{G2_REQUEST_JSON}}\n",
        encoding="utf-8",
    )
    return prompt_dir


def test_run_preflight_aggregates_all_checks_and_passes_on_clean_repo(tmp_path, clean_prompt_dir):
    report = run_preflight(
        Path("config/master_profile.yaml"), Path("profile/template.tex"),
        clean_prompt_dir, tmp_path, skip_render=True,
    )
    assert isinstance(report, PreflightReport)
    assert report.passed is True
    assert report.findings == ()


def test_run_preflight_against_the_real_repo_surfaces_exactly_the_known_shape_findings(tmp_path):
    """`run_preflight` (not just check_prompt_invariants directly) against
    the real repo's prompt directory must report only the two known shape
    defects -- no do_not_claim leak, no fence, no marker defect."""
    report = run_preflight(
        Path("config/master_profile.yaml"), Path("profile/template.tex"),
        Path("docs/prompts"), tmp_path, skip_render=True,
    )
    assert report.passed is False
    assert {f.surface for f in report.findings} == {"tailoring_s0.md", "tailoring_s1.md"}
    assert all(f.check == "prompt_invariants" for f in report.findings)


@pytest.mark.skipif(shutil.which("pdflatex") is None, reason="pdflatex not installed")
def test_real_variants_render_to_one_page_and_pass_l7(tmp_path, real_profile):
    findings = check_variants_render(real_profile, Path("profile/template.tex"), tmp_path)
    assert findings == ()


def test_broken_documented_shape_is_detected_for_s1(tmp_path):
    """The shape-parses check must be capable of catching a genuinely
    malformed example -- not just passing vacuously on anything."""
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    (prompt_dir / "tailoring_s1.md").write_text(
        "Required response shape:\n"
        '{\n  "must_have": "this should be a list, not a string"\n}\n'
        "\n{{S1_REQUEST_JSON}}\n",
        encoding="utf-8",
    )
    findings = check_prompt_invariants(prompt_dir)
    assert any("shape" in f.message.casefold() for f in findings)
