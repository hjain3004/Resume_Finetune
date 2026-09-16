"""L7 extension: rendered line counts, metric survival, emphasis rendering,
vertical bleed, invisible text, and the printable-margin advisory (M8P-5
Task 3). No pdflatex here -- every test runs against committed fixtures."""
import dataclasses
from pathlib import Path

import pytest

from src.render.l7 import (
    check_bullet_line_counts,
    check_bullets_survive,
    check_emphasis_rendered,
    check_metrics_survive,
    check_no_do_not_claim_in_pdf,
    check_no_invisible_text,
    check_printable_margin,
    check_within_page_vertical,
    run_l7_tailored,
)
from src.render.lines import parse_rendered_lines
from src.render.model import RenderBullet, RenderDoc, RenderEntry
from src.render.parse import parse_pdf
from tests.render.test_lines import EMPHASISED_FRAGMENT, THREE_LINE_BULLET_PLAIN, TWO_LINE_BULLET_PLAIN

FIXTURES = Path("tests/fixtures/render")

_ATS = {
    "forbidden_chars": [], "max_file_size_mb": 2.5, "max_pages": 1,
    "layout": {"columns": 1, "contact_in_body": True},
    "headings_whitelist": ["Education", "Experience", "Projects", "Technical Skills"],
}


def _bullet(bullet_id: str, text: str, *, emphasise: str | None = None) -> RenderBullet:
    spans = ()
    if emphasise is not None:
        start = text.index(emphasise)
        spans = ((start, start + len(emphasise)),)
    return RenderBullet(bullet_id=bullet_id, text=text, emphasis=spans)


def _doc(*, bullets, ats=None) -> RenderDoc:
    entry = RenderEntry(entry_id="p1", heading="Fixture Project", subheading="Python, FastAPI", bullets=tuple(bullets))
    return RenderDoc(
        identity={"name": "Test User"}, education=(), experience=(), projects=(entry,),
        skills={}, section_order=("Education", "Experience", "Projects", "Technical Skills"),
        ats=dict(ats) if ats is not None else dict(_ATS),
    )


@pytest.fixture
def two_line_doc():
    return _doc(bullets=[_bullet("b_modified", TWO_LINE_BULLET_PLAIN, emphasise=EMPHASISED_FRAGMENT)])


@pytest.fixture
def three_line_doc():
    return _doc(bullets=[_bullet("b_modified", THREE_LINE_BULLET_PLAIN, emphasise=EMPHASISED_FRAGMENT)])


@pytest.fixture
def two_line_doc_with_absent_bullet():
    return _doc(bullets=[_bullet("b_absent", "text that was never rendered anywhere on this page")])


@pytest.fixture
def doc_claiming_extra_metric():
    return _doc(bullets=[_bullet("b_modified", TWO_LINE_BULLET_PLAIN + " Also saved 99%.", emphasise=EMPHASISED_FRAGMENT)])


@pytest.fixture
def doc_claiming_unrendered_emphasis():
    # "between commercial bank" is real, rendered text -- but never bold.
    return _doc(bullets=[_bullet("b_modified", TWO_LINE_BULLET_PLAIN, emphasise="between commercial bank")])


@pytest.fixture
def doc_with_quarter_inch_floor():
    ats = dict(_ATS)
    ats["layout"] = {**_ATS["layout"], "min_margin_in": 0.25}
    return _doc(bullets=[_bullet("b_modified", TWO_LINE_BULLET_PLAIN, emphasise=EMPHASISED_FRAGMENT)], ats=ats)


def test_two_line_modified_bullet_passes(two_line_doc):
    pages = parse_rendered_lines(FIXTURES / "tailored_two_line.pdf")
    assert check_bullet_line_counts(two_line_doc, pages, frozenset({"b_modified"})) == []


def test_three_line_modified_bullet_violates(three_line_doc):
    pages = parse_rendered_lines(FIXTURES / "tailored_three_line.pdf")
    violations = check_bullet_line_counts(three_line_doc, pages, frozenset({"b_modified"}))
    assert len(violations) == 1
    assert "3 rendered lines" in violations[0]


def test_three_line_unmodified_bullet_is_exempt(three_line_doc):
    pages = parse_rendered_lines(FIXTURES / "tailored_three_line.pdf")
    assert check_bullet_line_counts(three_line_doc, pages, frozenset()) == []


def test_missing_bullet_reports_survival_not_a_line_count(two_line_doc_with_absent_bullet):
    pages = parse_rendered_lines(FIXTURES / "tailored_two_line.pdf")
    violations = check_bullet_line_counts(two_line_doc_with_absent_bullet, pages,
                                          frozenset({"b_absent"}))
    assert "did not survive" in violations[0]


def test_metrics_survive_passes_on_good_fixture(two_line_doc):
    assert check_metrics_survive(two_line_doc, parse_pdf(FIXTURES / "tailored_two_line.pdf")) == []


def test_metric_loss_is_detected(doc_claiming_extra_metric):
    violations = check_metrics_survive(doc_claiming_extra_metric,
                                       parse_pdf(FIXTURES / "tailored_two_line.pdf"))
    assert violations and "99%" in violations[0]


def test_emphasis_rendered_passes_when_bold_present(two_line_doc):
    pages = parse_rendered_lines(FIXTURES / "tailored_two_line.pdf")
    assert check_emphasis_rendered(two_line_doc, pages) == []


def test_emphasis_missing_from_pdf_is_detected(doc_claiming_unrendered_emphasis):
    pages = parse_rendered_lines(FIXTURES / "tailored_two_line.pdf")
    assert check_emphasis_rendered(doc_claiming_unrendered_emphasis, pages)


def test_vertical_bleed_is_detected(two_line_doc):
    assert check_within_page_vertical(two_line_doc, parse_pdf(FIXTURES / "tailored_bleed.pdf"))


def test_good_fixture_has_no_vertical_bleed(two_line_doc):
    assert check_within_page_vertical(two_line_doc, parse_pdf(FIXTURES / "tailored_two_line.pdf")) == []


def test_invisible_text_check_passes_on_visible_fixture(two_line_doc):
    pages = parse_rendered_lines(FIXTURES / "tailored_two_line.pdf")
    assert check_no_invisible_text(two_line_doc, pages) == []


def test_printable_margin_is_silent_when_unconfigured(two_line_doc):
    assert check_printable_margin(two_line_doc, parse_pdf(FIXTURES / "tailored_two_line.pdf")) == []


def test_printable_margin_flags_when_configured(doc_with_quarter_inch_floor):
    violations = check_printable_margin(doc_with_quarter_inch_floor,
                                        parse_pdf(FIXTURES / "tailored_two_line.pdf"))
    assert violations   # the 0.20in template is inside a 0.25in floor, by design


def test_do_not_claim_check_passes_when_the_term_is_absent():
    parsed = parse_pdf(FIXTURES / "tailored_two_line.pdf")
    assert check_no_do_not_claim_in_pdf(("Kubernetes",), parsed) == []


def test_do_not_claim_term_in_pdf_is_detected(doc_with_dnc):
    parsed = parse_pdf(FIXTURES / "real_resume_backend.pdf")
    assert check_no_do_not_claim_in_pdf(doc_with_dnc, parsed)


def test_run_l7_tailored_includes_every_base_l7_check(two_line_doc, monkeypatch):
    """The tailored aggregate must not silently drop an inherited check."""
    import src.render.l7 as l7
    called = []
    for name in ("check_identity_survives", "check_bullets_survive", "check_skills_survive",
                 "check_charset", "check_file_size", "check_page_count",
                 "check_single_column", "check_contact_in_body", "check_section_headings",
                 "check_no_overlap", "check_within_page"):
        original = getattr(l7, name)
        monkeypatch.setattr(l7, name,
                            lambda d, p, _n=name, _o=original: (called.append(_n), _o(d, p))[1])
    run_l7_tailored(two_line_doc, parse_pdf(FIXTURES / "tailored_two_line.pdf"),
                    parse_rendered_lines(FIXTURES / "tailored_two_line.pdf"), frozenset())
    assert len(called) == 11


# ---------------------------------------------------------------------------
# M8V-1 Task 3: validate L7 against a real rendered resume. The four toy
# fixtures above never wrap a bullet or interleave a date range -- they
# share an author with the code that checks them, so they share its blind
# spots. real_resume_backend.pdf is the real job-225 Notion chain (S1/S0/S2
# from tests/fixtures/tailor/traces/context.py, the real accepted
# zero-edit S3 response) rendered through the real production LaTeX arm
# with only identity/education-location scrubbed to synthetic placeholder
# values -- every bullet, wrap, and date range is real.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def real_resume_doc():
    import dataclasses

    from src.profile import load_profile
    from src.render.tailored import render_doc_from_draft
    from src.tailor.alignment_view import alignment_from_profile
    from src.tailor.s0 import build_s0_request, parse_s0_response
    from src.tailor.s1 import parse_s1_request, parse_s1_response
    from src.tailor.s2 import build_s2_request, parse_s2_response
    from src.tailor.s3 import build_s3_request, hydrate_s3, parse_s3_response
    from tests.fixtures.tailor.traces import context

    profile = load_profile("config/master_profile.yaml")
    s1_request = parse_s1_request(context.NOTION_S1_REQUEST)
    s1 = parse_s1_response(context.NOTION_S1_RESPONSE_RAW, s1_request.jd_text)
    s0_request = build_s0_request(s1_request.job_id, s1_request.company, s1_request.title, s1, profile.for_positioning())
    s0 = parse_s0_response(context.NOTION_S0_RESPONSE_RAW, s0_request)
    catalog = profile.for_selection("backend")
    s2_request = build_s2_request(s1_request.job_id, s1_request.company, s1_request.title, s1, s0, catalog)
    import sys; print('S1 MUST HAVE:', s1.must_have, file=sys.stderr); print('S2 COVERAGE:', context.NOTION_S2_RESPONSE_RAW, file=sys.stderr); s2 = parse_s2_response(context.NOTION_S2_RESPONSE_RAW, s2_request)
    alignment = alignment_from_profile(profile, s2_request, s2)
    s3_request = build_s3_request(s1_request.job_id, s1_request.company, s1_request.title, s1, s0, s2, alignment)

    s3_raw = Path("tests/fixtures/tailor/traces/s3_accepted.txt").read_text(encoding="utf-8")
    s3_response = parse_s3_response(s3_raw, s3_request)
    draft = hydrate_s3(s3_request, s3_response)

    # Same identity/education-location scrub used to record the fixture
    # (scripts/record_render_fixture.py real_resume_backend) -- neither
    # touches the alignment fingerprint, so the draft stays valid.
    scrubbed = dataclasses.replace(
        profile,
        identity={
            "name": "Test Candidate", "phone": "000-000-0000",
            "email": "test.candidate@example.com", "linkedin": "", "github": "",
            "location": "Testville, TS",
        },
        education=tuple(
            {**entry, **({"location": "Testville, TS"} if "location" in entry else {})}
            for entry in profile.education
        ),
    )
    return render_doc_from_draft(scrubbed, draft)


@pytest.fixture
def doc_claiming_absent_tail(real_resume_doc):
    """A genuinely fabricated bullet -- this text was never rendered
    anywhere in real_resume_backend.pdf. Proves the date-range fix does
    not blind check_bullets_survive to a real truncation."""
    return dataclasses.replace(
        real_resume_doc,
        projects=real_resume_doc.projects + (
            RenderEntry(entry_id="fabricated", heading="Fabricated Project", subheading="",
                       bullets=(RenderBullet(bullet_id="b_fabricated",
                                             text="This exact sentence was never printed anywhere on the page."),)),
        ),
    )


@pytest.fixture
def doc_claiming_false_emphasis(real_resume_doc):
    """Claims real, genuinely-rendered plain text is bold when it is not.
    Proves the line-wrap stitch does not blind check_emphasis_rendered to
    a real missing-bold defect."""
    target_bullet = next(b for b in real_resume_doc.all_bullets() if b.bullet_id == "sepsis_b2")
    fragment = "the best single model at 0.400 normalized utility"
    assert fragment in target_bullet.text
    start = target_bullet.text.index(fragment)
    fabricated_bullet = dataclasses.replace(
        target_bullet, emphasis=target_bullet.emphasis + ((start, start + len(fragment)),),
    )

    def _swap(entry):
        if any(b.bullet_id == "sepsis_b2" for b in entry.bullets):
            return dataclasses.replace(
                entry, bullets=tuple(fabricated_bullet if b.bullet_id == "sepsis_b2" else b for b in entry.bullets),
            )
        return entry

    return dataclasses.replace(real_resume_doc, projects=tuple(_swap(p) for p in real_resume_doc.projects))


@pytest.fixture
def doc_with_dnc():
    """"sepsis" genuinely appears in real_resume_backend.pdf -- used here
    as a stand-in do_not_claim term to prove the mechanism detects a term
    that is actually present, independent of the real profile's real
    do_not_claim list (which this specific chain's selected bullets do
    not happen to contain)."""
    return ("sepsis",)


def test_emphasis_survives_a_line_wrap(real_resume_doc):
    pages = parse_rendered_lines(FIXTURES / "real_resume_backend.pdf")
    assert check_emphasis_rendered(real_resume_doc, pages) == []


def test_bullet_survives_an_interleaved_date_range(real_resume_doc):
    parsed = parse_pdf(FIXTURES / "real_resume_backend.pdf")
    assert check_bullets_survive(real_resume_doc, parsed) == []


def test_genuine_truncation_is_still_detected(doc_claiming_absent_tail):
    parsed = parse_pdf(FIXTURES / "real_resume_backend.pdf")
    assert check_bullets_survive(doc_claiming_absent_tail, parsed)


def test_genuinely_unbolded_text_is_still_detected(doc_claiming_false_emphasis):
    pages = parse_rendered_lines(FIXTURES / "real_resume_backend.pdf")
    assert check_emphasis_rendered(doc_claiming_false_emphasis, pages)


def test_real_resume_passes_the_full_tailored_l7(real_resume_doc):
    parsed = parse_pdf(FIXTURES / "real_resume_backend.pdf")
    pages = parse_rendered_lines(FIXTURES / "real_resume_backend.pdf")
    assert run_l7_tailored(real_resume_doc, parsed, pages, frozenset()) == []
