"""Publication layout, naming, and render outcomes (M8P-5 Task 4). No
pdflatex is ever invoked -- render_latex is monkeypatched to copy a
committed PDF fixture. Uses a minimal, self-contained synthetic
MasterProfile/TailoredDraft pair (not the full real profile) so a small,
one-time recorded "good" fixture PDF can genuinely pass every L7 check
against it -- the full real profile's 13 bullets could never be made to
match a hand-verifiable fixture 1:1."""
import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from src.profile import Bullet, ClaimType, Experience, MasterProfile, Phrasings, Project
from src.render.tailored import _canonical_projection, _fingerprint
from src.tailor.publish import (
    RenderOutcomeKind,
    application_dir,
    parse_render_result,
    render_and_publish,
    render_result_to_dict,
    slugify,
)
from src.tailor.s3 import DraftBullet, TailoredDraft

FIXTURES = Path("tests/fixtures/render")
TEMPLATE = Path("profile/template.tex")

_ATS = {
    "forbidden_chars": [], "max_file_size_mb": 2.5, "max_pages": 1,
    "layout": {"columns": 1, "contact_in_body": True},
    "headings_whitelist": ["Education", "Experience", "Projects", "Technical Skills"],
    "filename_pattern": "Himanshu_Jain_Resume.pdf",
}


def _bullet(bullet_id: str, text: str) -> Bullet:
    return Bullet(id=bullet_id, claim_type=ClaimType.VERIFIED, priority=1,
                 phrasings=Phrasings(short=text), evidence=(), keywords_hit=(),
                 defense="", interview_risk="")


def _build_profile() -> MasterProfile:
    project = Project(id="fx_proj", name="Fixture Project", display_title="Fixture Project",
                      tech_line="Python", ownership_boundary="",
                      bullets=(_bullet("fx_b1", "Built the fixture pipeline end to end."),),
                      keywords_exact=(), keywords_topical=(), metric_ledger={}, metric_scope={},
                      known_gaps=(), display_date="Jan. 2026")
    experience = Experience(id="fx_exp", employer="Fixture Co.", title="Engineer", scope_line="",
                            display_date="Jan. 2026", ownership_boundary="",
                            bullets=(_bullet("fx_exp_b1", "Operated the fixture service in production."),),
                            keywords_exact=(), keywords_topical=(), metric_ledger={}, metric_scope={},
                            known_gaps=())
    return MasterProfile(
        schema_version="0.3.0", last_updated="2026-08-25",
        ats=dict(_ATS),
        identity={"name": "Fixture Person", "phone": "000-000-0000",
                 "email": "fixture@example.test", "location": "Remote"},
        education=({"institution": "Fixture University", "degree": "B.S. Fixture Studies",
                    "display_date": "2020", "location": "Remote"},),
        skills={"Languages": ("Python",)},
        projects=(project,), experience=(experience,), base_variants={},
        do_not_claim=(),
    )


@pytest.fixture(scope="module")
def profile() -> MasterProfile:
    return _build_profile()


def _signed_draft(profile: MasterProfile, *, base_variant: str) -> TailoredDraft:
    project_bullet = DraftBullet(bullet_id="fx_b1", owner_id="fx_proj", owner_kind="project",
                                 text="Built the fixture pipeline end to end.",
                                 plain_text="Built the fixture pipeline end to end.", emphasis=())
    experience_bullet = DraftBullet(bullet_id="fx_exp_b1", owner_id="fx_exp", owner_kind="experience",
                                    text="Operated the fixture service in production.",
                                    plain_text="Operated the fixture service in production.", emphasis=())
    unsigned = TailoredDraft(job_id=1, company="Acme", title="Fixture Role",
                             base_variant=base_variant, project_ids=("fx_proj",),
                             experience_ids=("fx_exp",), bullets=(experience_bullet, project_bullet),
                             skills=(("Languages", ("Python",)),), alignment_fingerprint="")
    fingerprint = _fingerprint(_canonical_projection(profile, unsigned))
    return replace(unsigned, alignment_fingerprint=fingerprint)


@pytest.fixture
def real_draft(profile) -> TailoredDraft:
    return _signed_draft(profile, base_variant="fixture")


@pytest.fixture
def other_draft(profile) -> TailoredDraft:
    """Same company/title (same application_dir) as real_draft, but a
    genuinely different alignment_fingerprint (base_variant differs)."""
    return _signed_draft(profile, base_variant="fixture_other")


@pytest.fixture
def tampered_draft(real_draft) -> TailoredDraft:
    return replace(real_draft, alignment_fingerprint="0" * 64)


@pytest.fixture
def stub_render_good_pdf(monkeypatch):
    """Recorded once at dev time by actually running render_doc_from_draft
    + render_latex over this exact fixture's profile/draft (see the
    recording note in the fixtures directory); genuinely passes every L7
    check against it."""
    def _fake_render(doc, template_path, out_pdf):
        out_pdf = Path(out_pdf)
        out_pdf.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(FIXTURES / "publish_good.pdf", out_pdf)
        out_pdf.with_suffix(".tex").write_text("% stub, not the real compiled source\n", encoding="utf-8")
        return out_pdf
    monkeypatch.setattr("src.tailor.publish.render_latex", _fake_render)


@pytest.fixture
def stub_render_bad_pdf(monkeypatch):
    def _fake_render(doc, template_path, out_pdf):
        out_pdf = Path(out_pdf)
        out_pdf.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(FIXTURES / "tailored_bleed.pdf", out_pdf)
        out_pdf.with_suffix(".tex").write_text("% stub, not the real compiled source\n", encoding="utf-8")
        return out_pdf
    monkeypatch.setattr("src.tailor.publish.render_latex", _fake_render)


def test_slugify_is_deterministic_and_ascii():
    assert slugify("Citadel Securities") == "citadel_securities"
    assert slugify("Software Engineer – University Graduate") == "software_engineer_university_graduate"
    assert slugify("  Notion  ") == "notion"


def test_application_dir_is_company_then_role(tmp_path):
    assert application_dir(tmp_path, "Notion", "SWE Early Career").name == "notion-swe_early_career"


def test_fingerprint_mismatch_publishes_nothing(profile, tampered_draft, tmp_path):
    outcome = render_and_publish(profile, tampered_draft, root=tmp_path,
                                 template_path=TEMPLATE,
                                 canonical_text_by_id={}, s3_bundle_schema_version="v1")
    assert outcome.kind is RenderOutcomeKind.FINGERPRINT_MISMATCH
    assert not list(tmp_path.rglob("render_result.json"))


def test_renderer_unavailable_is_typed(profile, real_draft, tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    outcome = render_and_publish(profile, real_draft, root=tmp_path,
                                 template_path=TEMPLATE,
                                 canonical_text_by_id={}, s3_bundle_schema_version="v1")
    assert outcome.kind is RenderOutcomeKind.RENDERER_UNAVAILABLE


def test_l7_failure_publishes_nothing(profile, real_draft, tmp_path, stub_render_bad_pdf):
    outcome = render_and_publish(profile, real_draft, root=tmp_path,
                                 template_path=TEMPLATE,
                                 canonical_text_by_id={}, s3_bundle_schema_version="v1")
    assert outcome.kind is RenderOutcomeKind.L7_FAILURE
    assert outcome.violations
    assert not list(tmp_path.rglob("render_result.json"))


def test_valid_publishes_commit_marker_last(profile, real_draft, tmp_path, stub_render_good_pdf):
    outcome = render_and_publish(profile, real_draft, root=tmp_path,
                                 template_path=TEMPLATE,
                                 canonical_text_by_id={}, s3_bundle_schema_version="v1")
    assert outcome.kind is RenderOutcomeKind.VALID
    directory = application_dir(tmp_path, real_draft.company, real_draft.title)
    for name in ("resume.tex", "Himanshu_Jain_Resume.pdf", "l7_report.json", "render_result.json"):
        assert (directory / name).exists()
    assert outcome.result.render_line_check == "pass"


def test_rerun_with_same_fingerprint_is_idempotent(profile, real_draft, tmp_path, stub_render_good_pdf):
    render_and_publish(profile, real_draft, root=tmp_path, template_path=TEMPLATE,
                       canonical_text_by_id={}, s3_bundle_schema_version="v1")
    marker = application_dir(tmp_path, real_draft.company, real_draft.title) / "render_result.json"
    before = marker.read_bytes()
    second = render_and_publish(profile, real_draft, root=tmp_path, template_path=TEMPLATE,
                                canonical_text_by_id={}, s3_bundle_schema_version="v1")
    assert second.kind is RenderOutcomeKind.ALREADY_PUBLISHED
    assert marker.read_bytes() == before


def test_different_fingerprint_refuses_rather_than_overwrites(profile, real_draft, other_draft,
                                                              tmp_path, stub_render_good_pdf):
    render_and_publish(profile, real_draft, root=tmp_path, template_path=TEMPLATE,
                       canonical_text_by_id={}, s3_bundle_schema_version="v1")
    marker = application_dir(tmp_path, real_draft.company, real_draft.title) / "render_result.json"
    before = marker.read_bytes()
    outcome = render_and_publish(profile, other_draft, root=tmp_path, template_path=TEMPLATE,
                                 canonical_text_by_id={}, s3_bundle_schema_version="v1")
    assert outcome.kind is RenderOutcomeKind.CONFLICT
    assert marker.read_bytes() == before


def test_render_result_round_trips_strictly(profile, real_draft, tmp_path, stub_render_good_pdf):
    outcome = render_and_publish(profile, real_draft, root=tmp_path, template_path=TEMPLATE,
                                 canonical_text_by_id={}, s3_bundle_schema_version="v1")
    assert parse_render_result(render_result_to_dict(outcome.result)) == outcome.result


def test_publish_module_never_imports_the_model_boundary():
    source = Path("src/tailor/publish.py").read_text(encoding="utf-8")
    assert "src.tailor.invoke" not in source
    assert "src.llm_trace" not in source


# ---------------------------------------------------------------------------
# M8N-0: explicit directory override and rejected output on L7 failure
# ---------------------------------------------------------------------------


def test_directory_override_is_used_instead_of_derived_dir(profile, real_draft, tmp_path, stub_render_good_pdf):
    target = tmp_path / "custom" / "acme-fixture_role-second"
    outcome = render_and_publish(profile, real_draft, root=tmp_path, template_path=TEMPLATE,
                                 canonical_text_by_id={}, s3_bundle_schema_version="v1",
                                 directory=target)
    assert outcome.kind is RenderOutcomeKind.VALID
    assert (target / "render_result.json").exists()
    assert not application_dir(tmp_path, "Acme", "Fixture Role").exists()


def test_l7_failure_writes_rejected_artifacts_and_no_marker(profile, real_draft, tmp_path, stub_render_bad_pdf):
    target = tmp_path / "acme-fixture_role"
    reject = target / "rejected"
    outcome = render_and_publish(profile, real_draft, root=tmp_path, template_path=TEMPLATE,
                                 canonical_text_by_id={}, s3_bundle_schema_version="v1",
                                 directory=target, reject_dir=reject)
    assert outcome.kind is RenderOutcomeKind.L7_FAILURE
    assert outcome.violations
    assert (reject / "resume.tex").exists()
    assert (reject / profile.ats["filename_pattern"]).exists()
    assert json.loads((reject / "l7_report.json").read_text(encoding="utf-8")) == list(outcome.violations)
    assert not (target / "render_result.json").exists()


def test_l7_failure_without_reject_dir_writes_nothing(profile, real_draft, tmp_path, stub_render_bad_pdf):
    outcome = render_and_publish(profile, real_draft, root=tmp_path, template_path=TEMPLATE,
                                 canonical_text_by_id={}, s3_bundle_schema_version="v1")
    assert outcome.kind is RenderOutcomeKind.L7_FAILURE
    assert not list(tmp_path.rglob("rejected"))
    assert not list(tmp_path.rglob("*.tex"))
