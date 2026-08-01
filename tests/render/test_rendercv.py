from src.render.rendercv import emit_rendercv_yaml
from src.render.model import RenderBullet, RenderDoc, RenderEntry


def _doc() -> RenderDoc:
    return RenderDoc(
        identity={"name": "Test User", "email": "a@b.edu",
                  "phone": "408-000-0000", "location": "San Jose, CA"},
        education=(),
        experience=(RenderEntry(
            entry_id="e1", heading="Acme", subheading="Engineer",
            date_range="Aug. 2023 - May 2025",
            bullets=(RenderBullet(bullet_id="b1", text="Cut p99 by 40%."),),
        ),),
        projects=(),
        skills={"languages": ("Python",)},
        section_order=("Experience", "Skills"),
        ats={"headings_whitelist": ["Education", "Experience", "Projects", "Skills"]},
    )


def test_yaml_carries_identity():
    out = emit_rendercv_yaml(_doc())
    assert out["cv"]["name"] == "Test User"
    assert out["cv"]["email"] == "a@b.edu"


def test_yaml_carries_bullet_text_without_ids():
    dumped = str(emit_rendercv_yaml(_doc()))
    assert "Cut p99 by 40%." in dumped
    assert "b1" not in dumped


def test_only_requested_sections_are_emitted():
    sections = emit_rendercv_yaml(_doc())["cv"]["sections"]
    assert set(sections) == {"experience", "skills"}


def test_single_column_theme_is_forced():
    out = emit_rendercv_yaml(_doc())
    assert out["design"]["theme"] in {"classic", "engineeringresumes", "sb2nov"}
