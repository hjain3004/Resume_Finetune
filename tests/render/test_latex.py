from src.render.latex import _humanize_skill_category, emit_latex_body, escape_latex
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


def test_unsupported_latex_chars_are_not_escaped():
    # If a character isn't in _LATEX_ESCAPES, it passes through untouched
    assert escape_latex("hello * world") == "hello * world"


def _bullet(raw: str) -> RenderBullet:
    from src.render.emphasis import parse_emphasis
    plain, spans = parse_emphasis(raw)
    return RenderBullet(bullet_id="b1", text=plain, emphasis=spans)


def test_plain_bullet_emits_no_textbf():
    from src.render.latex import _emphasized
    assert _emphasized(_bullet("Cut p99 by 40 percent.")) == "Cut p99 by 40 percent."


def test_emphasized_span_is_wrapped_in_textbf():
    from src.render.latex import _emphasized
    assert _emphasized(_bullet("Cut **p99 latency** here.")) == (
        r"Cut \textbf{p99 latency} here."
    )


def test_latex_special_inside_an_emphasized_span_is_escaped():
    from src.render.latex import _emphasized
    assert _emphasized(_bullet("**Cut p99 by 40%** now.")) == (
        r"\textbf{Cut p99 by 40\%} now."
    )


def test_latex_special_outside_an_emphasized_span_is_escaped():
    from src.render.latex import _emphasized
    assert _emphasized(_bullet("Cut **p99** by 40% & held.")) == (
        r"Cut \textbf{p99} by 40\% \& held."
    )


def test_span_at_string_start_and_end():
    from src.render.latex import _emphasized
    assert _emphasized(_bullet("**alpha** mid **omega**")) == (
        r"\textbf{alpha} mid \textbf{omega}"
    )


def test_ampersand_and_underscore_are_escaped():
    assert escape_latex("R&D_team") == r"R\&D\_team"


def test_body_contains_bullet_text_but_not_bullet_ids():
    body = emit_latex_body(_doc())
    assert r"Cut p99 by 40\%." in body
    assert "b1" not in body, "bullet ids must be stripped at render"


def test_body_emits_sections_in_order():
    body = emit_latex_body(_doc())
    assert body.index("Projects") < body.index("Skills")


def test_experience_heading_leads_with_title_and_tech_then_employer():
    from dataclasses import replace
    doc = replace(
        _doc(),
        projects=(),
        experience=(RenderEntry(
            entry_id="e1", heading="Acme Ltd.", subheading="Software Developer",
            date_range="2023 - 2025", tech_line="Java, Spring Boot",
        ),),
        section_order=("Experience",),
    )
    body = emit_latex_body(doc)
    assert (
        r"\resumeSubheading{Software Developer\textnormal{ $|$ \emph{\small Java, Spring Boot}}}"
        r"{2023 - 2025}{Acme Ltd.}{}"
    ) in body


def test_experience_heading_without_tech_line_has_no_separator():
    from dataclasses import replace
    doc = replace(
        _doc(),
        projects=(),
        experience=(RenderEntry(entry_id="e1", heading="Acme", subheading="Engineer"),),
        section_order=("Experience",),
    )
    assert r"\resumeSubheading{Engineer}{}{Acme}{}" in emit_latex_body(doc)


def test_humanize_skill_category_maps_known_keys():
    assert _humanize_skill_category("ai_and_machine_learning") == "AI and Machine Learning"
    assert _humanize_skill_category("languages") == "Languages"
    assert _humanize_skill_category("frameworks") == "Frameworks"
    assert _humanize_skill_category("libraries") == "Libraries"
    assert _humanize_skill_category("apis_and_standards") == "APIs and Standards"
    assert _humanize_skill_category("developer_tools") == "Developer Tools"
    assert _humanize_skill_category("databases") == "Databases"


def test_skills_block_emits_human_label_not_raw_key():
    from dataclasses import replace
    doc = replace(
        _doc(),
        projects=(),
        skills={"ai_and_machine_learning": ("PyTorch",), "developer_tools": ("Git",)},
        section_order=("Skills",),
    )
    body = emit_latex_body(doc)
    assert r"\textbf{AI and Machine Learning}: PyTorch" in body
    assert r"\textbf{Developer Tools}: Git" in body
    assert "ai_and_machine_learning" not in body
    assert "developer_tools" not in body
