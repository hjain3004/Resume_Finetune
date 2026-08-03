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


def _bullet(raw: str) -> RenderBullet:
    from src.render.emphasis import parse_emphasis
    plain, spans = parse_emphasis(raw)
    return RenderBullet(bullet_id="b1", text=plain, emphasis=spans)


def test_markdown_no_spans_returns_plain():
    from src.render.rendercv import _markdown
    assert _markdown(_bullet("Cut p99 by 40 percent.")) == "Cut p99 by 40 percent."


def test_markdown_one_span_wraps_in_stars():
    from src.render.rendercv import _markdown
    assert _markdown(_bullet("Cut **p99 latency** here.")) == "Cut **p99 latency** here."


def test_markdown_multiple_spans():
    from src.render.rendercv import _markdown
    assert _markdown(_bullet("**alpha** mid **omega**")) == "**alpha** mid **omega**"


def test_render_rendercv_subprocess_contract(monkeypatch, tmp_path):
    import subprocess
    from src.render.rendercv import render_rendercv

    calls = []

    def mock_run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(subprocess, "run", mock_run)

    out_pdf = tmp_path / "out" / "resume.pdf"
    res = render_rendercv(_doc(), out_pdf)

    assert res == out_pdf
    
    # Check that it writes the YAML
    yaml_path = out_pdf.with_suffix(".yaml")
    assert yaml_path.exists()
    assert "Test User" in yaml_path.read_text()

    assert len(calls) == 1
    args, kwargs = calls[0]
    
    # check that rendercv is invoked absolutely from repo
    from pathlib import Path
    assert args[0] == str(Path(".venv/bin/rendercv").resolve())
    assert args[1] == "render"
    assert args[2] == "resume.yaml"  # passed by name
    assert args[3] == "--pdf-path"
    assert args[4] == "resume.pdf"   # output file name
    
    assert kwargs.get("cwd") == str(out_pdf.parent)
    assert kwargs.get("check") is True

