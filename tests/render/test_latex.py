from src.render.latex import emit_latex_body, escape_latex
from src.render.model import RenderBullet, RenderDoc, RenderEntry


def _doc() -> RenderDoc:
    return RenderDoc(
        identity={"name": "Test User", "email": "a@b.edu"},
        education=(),
        experience=(),
        projects=(RenderEntry(
            entry_id="p1", heading="PeerChat", subheading="Go",
            bullets=(RenderBullet(bullet_id="b1", text="Cut p99 by 40%."),),
        ),),
        skills={"languages": ("Python",)},
        section_order=("Projects", "Skills"),
        ats={"headings_whitelist": ["Education", "Experience", "Projects", "Skills"]},
    )


def test_percent_is_escaped():
    assert escape_latex("Cut p99 by 40%.") == r"Cut p99 by 40\%."


def test_ampersand_and_underscore_are_escaped():
    assert escape_latex("R&D_team") == r"R\&D\_team"


def test_body_contains_bullet_text_but_not_bullet_ids():
    body = emit_latex_body(_doc())
    assert r"Cut p99 by 40\%." in body
    assert "b1" not in body, "bullet ids must be stripped at render"


def test_body_emits_sections_in_order():
    body = emit_latex_body(_doc())
    assert body.index("Projects") < body.index("Skills")
