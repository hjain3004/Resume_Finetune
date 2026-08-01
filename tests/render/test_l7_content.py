from src.render.l7 import (
    check_identity_survives, check_bullets_survive,
    check_skills_survive, check_charset, check_file_size,
)
from src.render.model import RenderBullet, RenderDoc, RenderEntry
from src.render.parse import ParsedPdf, TextBox


def _parsed(text: str, size_bytes: int = 1000) -> ParsedPdf:
    return ParsedPdf(
        boxes=(TextBox(text=text, x0=50, y0=100, x1=550, y1=120, page=0),),
        page_height=792.0, page_width=612.0, size_bytes=size_bytes,
    )


def _doc(**kw) -> RenderDoc:
    base = dict(
        identity={"name": "Test User", "email": "a@b.edu",
                  "phone": "408-000-0000", "location": "San Jose, CA"},
        education=(), experience=(), projects=(),
        skills={"languages": ("Python",)},
        section_order=("Skills",),
        ats={"forbidden_chars": ["–", "’"], "max_file_size_mb": 2.5},
    )
    base.update(kw)
    return RenderDoc(**base)


def test_identity_survives_when_all_fields_present():
    parsed = _parsed("Test User a@b.edu 408-000-0000 San Jose, CA")
    assert check_identity_survives(_doc(), parsed) == []


def test_missing_phone_is_reported():
    parsed = _parsed("Test User a@b.edu San Jose, CA")
    violations = check_identity_survives(_doc(), parsed)
    assert len(violations) == 1
    assert "phone" in violations[0]


def test_dropped_bullet_is_reported():
    entry = RenderEntry(
        entry_id="p1", heading="Proj", subheading="Go",
        bullets=(RenderBullet(bullet_id="b1", text="Built an event store."),
                 RenderBullet(bullet_id="b2", text="Cut latency by 40 percent.")),
    )
    violations = check_bullets_survive(_doc(projects=(entry,)),
                                       _parsed("Built an event store."))
    assert len(violations) == 1
    assert "b2" in violations[0]


def test_bullet_survival_tolerates_line_wrapping():
    entry = RenderEntry(
        entry_id="p1", heading="Proj", subheading="Go",
        bullets=(RenderBullet(bullet_id="b1", text="Built an event store."),),
    )
    assert check_bullets_survive(_doc(projects=(entry,)),
                                 _parsed("Built   an\nevent  store.")) == []


def test_missing_skill_term_is_reported():
    doc = _doc(skills={"languages": ("Python", "Rust")})
    violations = check_skills_survive(doc, _parsed("Python"))
    assert len(violations) == 1
    assert "Rust" in violations[0]


def test_forbidden_char_is_reported():
    violations = check_charset(_doc(), _parsed("Reduced latency – by half"))
    assert len(violations) == 1


def test_clean_charset_passes():
    assert check_charset(_doc(), _parsed("Reduced latency - by half")) == []


def test_oversize_file_is_reported():
    assert len(check_file_size(_doc(), _parsed("ok", size_bytes=3 * 1024 * 1024))) == 1


def test_within_size_limit_passes():
    assert check_file_size(_doc(), _parsed("ok", size_bytes=500 * 1024)) == []
