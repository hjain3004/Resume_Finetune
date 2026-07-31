# M10 — Rendering decision gate + parseability CI: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the declared `ats:` policy in `config/master_profile.yaml` into a mechanically enforced L7 parseability gate over rendered PDFs, and record a renderer decision via a bake-off.

**Architecture:** A pure, immutable `RenderDoc` intermediate representation sits between the master profile and any renderer. Both bake-off arms (existing LaTeX, RenderCV) consume it, which makes the renderer choice reversible. L7 compares the `RenderDoc` (what we meant to say) against the `pdfminer.six`-parsed PDF (what an ATS actually sees).

**Tech Stack:** Python 3.11+, `pdfminer.six` (new runtime dep), RenderCV + Typst (bake-off only), `pytest`. Node/OpenResume is an opt-in oracle and must never be required by `pytest -q`.

**Spec:** `docs/superpowers/specs/2026-07-31-m10-render-parseability-design.md`

## Global Constraints

- Python 3.11+, type hints everywhere, dataclasses over dicts at module boundaries.
- Small pure functions; parsing separated from I/O so parsers are testable on fixtures.
- No `print` inside `src/`; logging via `logging` (INFO to stderr). CLI output belongs in `scripts/`.
- Tests never touch the network. Fixtures live in `tests/fixtures/`.
- `src/tailor/lint.py` is **not modified** by this milestone and must stay dependency-free.
- M10 writes **no SQLite** and does not change scoring, discovery, or G1 (L1–L6).
- Every `check_*` function returns `list[str]` of violations (empty list = pass), matching `src/tailor/lint.py`.
- UTC ISO-8601 timestamps in storage.
- `pytest -q` must stay green **with no Node installed**.
- Approved deps for this milestone only: `pdfminer.six` (runtime), RenderCV+Typst (bake-off), OpenResume/Node (opt-in oracle). Nothing else without asking.
- Baseline before starting: **785 tests passing**. Use `.venv/bin/python` and `.venv/bin/pytest` — bare `python3` lacks PyYAML.

---

### Task 0: Declare dependencies and the oracle marker

**Files:**
- Modify: `CLAUDE.md` (prime directive 4 dependency list)
- Modify: `pyproject.toml` or `requirements.txt` (whichever the repo already uses — check before editing)
- Modify: `pyproject.toml` `[tool.pytest.ini_options]` (create the table if absent)

**Interfaces:**
- Consumes: nothing.
- Produces: a registered `oracle` pytest marker that Task 9 uses; `pdfminer.six` importable.

- [ ] **Step 1: Find where dependencies are currently declared**

Run: `ls pyproject.toml setup.py requirements*.txt 2>/dev/null; grep -rn "trafilatura" --include=pyproject.toml --include=*.txt .`
Do not guess — edit the file that actually exists.

- [ ] **Step 2: Add `pdfminer.six` to the runtime dependency list**

Add `pdfminer.six>=20231228` alongside the existing `requests`, `trafilatura`, `PyYAML`, `crawl4ai` entries.

- [ ] **Step 3: Register the `oracle` marker**

In `[tool.pytest.ini_options]`:

```toml
markers = [
    "oracle: opt-in Tier B parser cross-check; requires Node. Deselected by default.",
]
addopts = "-m 'not oracle'"
```

- [ ] **Step 4: Update CLAUDE.md prime directive 4**

Change the approved list to read: `requests, trafilatura, PyYAML, pytest, crawl4ai (M6.5 tier-2 resolver), pdfminer.six (M10 L7 gate)`. Add a sentence: `RenderCV/Typst are bake-off-only and become runtime deps only if adopted by the M10 decision; Node/OpenResume is an opt-in test oracle and must never be required by pytest -q.`

- [ ] **Step 5: Install and verify**

Run: `.venv/bin/pip install "pdfminer.six>=20231228" && .venv/bin/python -c "from pdfminer.high_level import extract_pages; print('ok')"`
Expected: `ok`

- [ ] **Step 6: Verify the marker deselects cleanly**

Run: `.venv/bin/pytest -q`
Expected: 785 passed (unchanged — no tests added yet, and `addopts` must not break collection).

- [ ] **Step 7: Commit**

```bash
git add CLAUDE.md pyproject.toml
git commit -m "chore(m10): add pdfminer.six dep and oracle pytest marker"
```

---

### Task 0b: HUMAN DECISION — reconcile template vs profile contracts

**Three conflicts between the real template and `master_profile.yaml` must be settled before
Task 2, or `build_render_doc` raises on the user's own resume. Ask the user; do not choose
unilaterally, and never resolve one by weakening a check.**

**Files:**
- Modify: `config/master_profile.yaml` (whichever of the three the user approves)
- Modify: `src/profile.py` only if conflict 2 is resolved by adding a field
- Modify: `docs/DECISIONS.md`

- [ ] **Step 1: Present the three conflicts and get decisions**

1. **`Technical Skills` vs `Skills`.** The template emits `\section{Technical Skills}`;
   `ats.headings_whitelist` (`config/master_profile.yaml:59`) lists `Skills`.
   *Recommended:* add `Technical Skills` to the whitelist. It is a standard ATS-safe
   heading and the template is the interview-tested artifact. Do **not** rename the
   template's section to match the config.
2. **Project dates.** `\resumeProjectHeading`'s second argument is a date range, but
   `Project` (`src/profile.py:237-248`) has no date field. *Options:* add an optional
   `display_date` to `Project` and the YAML, or render projects with an empty date.
3. **`AI/ML` skills category.** The template's skills line includes `AI/ML`
   (LLM Integration, Prompt Engineering, AI Agent Design, Structured Output Parsing);
   `config/master_profile.yaml:87-93` has no such category, so rendering from the profile
   silently drops it. *Options:* add an `ai_ml` category, or accept the omission.

- [ ] **Step 2: Apply the approved changes**

If conflict 1 is resolved as recommended, `ats.headings_whitelist` becomes
`["Education", "Experience", "Projects", "Skills", "Technical Skills"]`, and
`_SECTION_ORDER` in Task 2 uses `"Technical Skills"` as its fourth element.

- [ ] **Step 3: Verify the profile still loads and record the decisions**

Run: `.venv/bin/python -m scripts.validate_profile`
Expected: OK, 5 projects, 47 bullets (4 blocked), base_variants backend and ml.

Run: `.venv/bin/pytest -q`
Expected: 785 passed.

Append a dated `docs/DECISIONS.md` entry recording all three resolutions and their rationale.

- [ ] **Step 4: Commit**

```bash
git add config/master_profile.yaml src/profile.py docs/DECISIONS.md
git commit -m "fix(m10): reconcile template section names and skills with master profile"
```

---

### Task 1: The RenderDoc IR

**Files:**
- Create: `src/render/__init__.py` (empty)
- Create: `src/render/model.py`
- Test: `tests/render/__init__.py` (empty), `tests/render/test_model.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `RenderBullet`, `RenderEntry`, `RenderDoc` — all frozen dataclasses. Every later task imports these from `src.render.model`.

> **Do not forget `src/render/__init__.py` and `tests/render/__init__.py`.** Missing package markers were a real defect in this repo during M8: the suite passed locally while the package was unimportable from a clean checkout. Create both as empty files and `git add` them explicitly.

- [ ] **Step 1: Write the failing test**

```python
# tests/render/test_model.py
import dataclasses
import pytest
from src.render.model import RenderBullet, RenderEntry, RenderDoc


def test_render_entry_defaults_are_empty():
    entry = RenderEntry(entry_id="pc", heading="PeerChat", subheading="Go, gRPC")
    assert entry.date_range == ""
    assert entry.location == ""
    assert entry.bullets == ()


def test_render_doc_is_frozen():
    doc = RenderDoc(
        identity={"name": "Test User"},
        education=(),
        experience=(),
        projects=(),
        skills={"languages": ("Python",)},
        section_order=("Education", "Skills"),
        ats={},
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        doc.identity = {}


def test_render_bullet_carries_id_for_traceability():
    bullet = RenderBullet(bullet_id="pc_b01_event_sourcing", text="Built an event store.")
    assert bullet.bullet_id == "pc_b01_event_sourcing"
    assert bullet.text == "Built an event store."
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/render/test_model.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.render'`

- [ ] **Step 3: Write the implementation**

```python
# src/render/model.py
"""Renderer-agnostic intermediate representation. No I/O, no rendering."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RenderBullet:
    """One bullet. `bullet_id` carries G0 traceability to the renderer boundary."""

    bullet_id: str
    text: str


@dataclass(frozen=True)
class RenderEntry:
    """One education / experience / project entry.

    Defaults are empty because the sources are genuinely asymmetric: projects
    carry no date, and neither projects nor experience carry a location.
    """

    entry_id: str
    heading: str
    subheading: str
    date_range: str = ""
    location: str = ""
    bullets: tuple[RenderBullet, ...] = ()


@dataclass(frozen=True)
class RenderDoc:
    """What we intend the PDF to say. L7 asserts the PDF actually says it."""

    identity: dict[str, str]
    education: tuple[RenderEntry, ...]
    experience: tuple[RenderEntry, ...]
    projects: tuple[RenderEntry, ...]
    skills: dict[str, tuple[str, ...]]
    section_order: tuple[str, ...]
    ats: dict[str, Any]

    def all_bullets(self) -> tuple[RenderBullet, ...]:
        """Every bullet across all sections, in document order."""
        return tuple(
            bullet
            for group in (self.education, self.experience, self.projects)
            for entry in group
            for bullet in entry.bullets
        )

    def all_skill_terms(self) -> tuple[str, ...]:
        return tuple(term for terms in self.skills.values() for term in terms)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/render/test_model.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/render/__init__.py src/render/model.py tests/render/__init__.py tests/render/test_model.py
git commit -m "feat(m10): add RenderDoc intermediate representation"
```

---

### Task 2: Profile → RenderDoc mapping

**Files:**
- Create: `src/render/mapping.py`
- Test: `tests/render/test_mapping.py`

**Interfaces:**
- Consumes: `RenderBullet`, `RenderEntry`, `RenderDoc` from `src.render.model`; `MasterProfile`, `load_profile` from `src.profile`.
- Produces: `build_render_doc(profile: MasterProfile, base_variant: str, tier_overrides: dict[str, str] | None = None) -> RenderDoc` and `RenderMappingError(ValueError)`.

**Background the implementer needs:**
`MasterProfile` (`src/profile.py:637`) exposes `identity`, `education` (tuple of dicts with keys `institution`, `degree`, `location`, `display_date`), `skills` (dict of category → tuple of terms), `projects` (tuple of `Project`), `experience` (tuple of `Experience`), `base_variants`, and `ats`.
`Project` has `id`, `display_title`, `tech_line`, `bullets`. `Experience` has `id`, `employer`, `title`, `display_date`, `bullets`.
`Phrasings` has `short: str` (always present) and `medium: str | None`, `long: str | None`.
`MasterProfile._ordered_bullets(base_variant)` returns `((ownership_boundary, Bullet), ...)` in `bullet_order` order and raises `ProfileValidationError` for an unknown variant.

- [ ] **Step 1: Write the failing tests**

```python
# tests/render/test_mapping.py
import pytest
from src.profile import load_profile
from src.render.mapping import build_render_doc, RenderMappingError

PROFILE = load_profile("config/master_profile.yaml")


def test_backend_variant_maps_all_ordered_bullets():
    doc = build_render_doc(PROFILE, "backend")
    ordered = PROFILE.base_variants["backend"].bullet_order
    assert [b.bullet_id for b in doc.all_bullets()] == list(ordered)


def test_projects_have_no_date_and_experience_does():
    doc = build_render_doc(PROFILE, "backend")
    assert all(p.date_range == "" for p in doc.projects)
    assert all(e.date_range != "" for e in doc.experience)


def test_section_order_is_subset_of_headings_whitelist():
    doc = build_render_doc(PROFILE, "backend")
    whitelist = set(PROFILE.ats["headings_whitelist"])
    assert set(doc.section_order) <= whitelist


def test_tier_override_selects_requested_phrasing():
    ordered = PROFILE.base_variants["backend"].bullet_order
    target = ordered[0]
    doc = build_render_doc(PROFILE, "backend", tier_overrides={target: "short"})
    rendered = {b.bullet_id: b.text for b in doc.all_bullets()}
    index = {b.id: b for src in (*PROFILE.projects, *PROFILE.experience) for b in src.bullets}
    assert rendered[target] == index[target].phrasings.short


def test_unavailable_tier_is_a_hard_error_not_a_silent_downgrade():
    index = {b.id: b for src in (*PROFILE.projects, *PROFILE.experience) for b in src.bullets}
    ordered = set(PROFILE.base_variants["backend"].bullet_order)
    missing = next(
        (bid for bid, b in index.items() if bid in ordered and b.phrasings.long is None),
        None,
    )
    if missing is None:
        pytest.skip("every ordered bullet defines a long phrasing; nothing to assert")
    with pytest.raises(RenderMappingError, match="long"):
        build_render_doc(PROFILE, "backend", tier_overrides={missing: "long"})


def test_override_for_unknown_bullet_id_raises():
    with pytest.raises(RenderMappingError, match="absent"):
        build_render_doc(PROFILE, "backend", tier_overrides={"no_such_bullet": "short"})


def test_unknown_base_variant_raises():
    with pytest.raises(Exception):
        build_render_doc(PROFILE, "does_not_exist")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/render/test_mapping.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.render.mapping'`

- [ ] **Step 3: Write the implementation**

```python
# src/render/mapping.py
"""Pure mapping from the validated master profile to the render IR."""

import logging
import re

from src.profile import MasterProfile
from src.render.model import RenderBullet, RenderDoc, RenderEntry

logger = logging.getLogger(__name__)

_TIER_FALLBACK = ("medium", "short")
_SECTION_ORDER = ("Education", "Experience", "Projects", "Skills")


class RenderMappingError(ValueError):
    """Raised when the profile cannot be mapped without losing content."""


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")


def _resolve_text(bullet, requested: str | None) -> str:
    """Pick the phrasing. A requested-but-absent tier is an error, not a downgrade."""
    if requested is not None:
        if requested not in ("short", "medium", "long"):
            raise RenderMappingError(
                f"bullet {bullet.id!r}: unknown phrasing tier {requested!r}"
            )
        text = getattr(bullet.phrasings, requested, None)
        if text is None:
            raise RenderMappingError(
                f"bullet {bullet.id!r}: requested phrasing tier {requested!r} is not "
                f"defined; refusing to silently substitute another tier"
            )
        return text
    for tier in _TIER_FALLBACK:
        text = getattr(bullet.phrasings, tier, None)
        if text is not None:
            return text
    return bullet.phrasings.short


def build_render_doc(
    profile: MasterProfile,
    base_variant: str,
    tier_overrides: dict[str, str] | None = None,
) -> RenderDoc:
    """Resolve a base variant into the renderer-agnostic IR.

    Raises RenderMappingError if a bullet id is unresolvable, an override names
    an unknown bullet, or a section name is not permitted by the ATS whitelist.
    """
    overrides = tier_overrides or {}

    # _ordered_bullets raises ProfileValidationError for an unknown variant.
    ordered = profile._ordered_bullets(base_variant)
    wanted_ids = [bullet.id for _, bullet in ordered]

    unknown_overrides = set(overrides) - set(wanted_ids)
    if unknown_overrides:
        raise RenderMappingError(
            f"tier_overrides reference bullet ids absent from base_variant "
            f"{base_variant!r}: {sorted(unknown_overrides)}"
        )

    selected = {
        bullet.id: RenderBullet(
            bullet_id=bullet.id,
            text=_resolve_text(bullet, overrides.get(bullet.id)),
        )
        for _, bullet in ordered
    }

    def _entry_bullets(source_bullets) -> tuple[RenderBullet, ...]:
        return tuple(selected[b.id] for b in source_bullets if b.id in selected)

    variant_projects = set(profile.base_variants[base_variant].projects)
    projects = tuple(
        RenderEntry(
            entry_id=project.id,
            heading=project.display_title,
            subheading=project.tech_line,
            bullets=_entry_bullets(project.bullets),
        )
        for project in profile.projects
        if project.id in variant_projects
    )

    experience = tuple(
        RenderEntry(
            entry_id=exp.id,
            heading=exp.employer,
            subheading=exp.title,
            date_range=exp.display_date,
            bullets=_entry_bullets(exp.bullets),
        )
        for exp in profile.experience
    )

    education = tuple(
        RenderEntry(
            entry_id=_slugify(item["institution"]),
            heading=item["institution"],
            subheading=item["degree"],
            date_range=item.get("display_date", ""),
            location=item.get("location", ""),
        )
        for item in profile.education
    )

    emitted = [
        bullet.bullet_id
        for group in (education, experience, projects)
        for entry in group
        for bullet in entry.bullets
    ]
    missing = set(wanted_ids) - set(emitted)
    if missing:
        raise RenderMappingError(
            f"base_variant {base_variant!r} orders bullet ids that no project or "
            f"experience in this variant owns: {sorted(missing)}"
        )

    whitelist = set(profile.ats.get("headings_whitelist", ()))
    illegal = [name for name in _SECTION_ORDER if name not in whitelist]
    if illegal:
        raise RenderMappingError(
            f"section name(s) {illegal} absent from ats.headings_whitelist "
            f"{sorted(whitelist)}"
        )

    return RenderDoc(
        identity=dict(profile.identity),
        education=education,
        experience=experience,
        projects=projects,
        skills={k: tuple(v) for k, v in profile.skills.items()},
        section_order=_SECTION_ORDER,
        ats=dict(profile.ats),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/render/test_mapping.py -v`
Expected: 7 passed (one may skip)

**If `test_backend_variant_maps_all_ordered_bullets` fails on ordering:** `all_bullets()` walks education → experience → projects, but `bullet_order` interleaves by its own sequence. If the real profile's `bullet_order` does not group by section, relax that test to compare **sets** and add a separate test asserting per-entry order is preserved. Do not reorder `bullet_order` to satisfy the test — the profile is authoritative.

- [ ] **Step 5: Verify bullet count end to end**

Run: `.venv/bin/python -c "
from src.profile import load_profile
from src.render.mapping import build_render_doc
p = load_profile('config/master_profile.yaml')
d = build_render_doc(p, 'backend')
print(len(d.all_bullets()), 'bullets;', len(d.projects), 'projects;', len(d.experience), 'experience')
print('expected bullets:', len(p.base_variants['backend'].bullet_order))
"`
Expected: the two bullet counts match.

- [ ] **Step 6: Commit**

```bash
git add src/render/mapping.py tests/render/test_mapping.py
git commit -m "feat(m10): map master profile to RenderDoc"
```

---

### Task 3: PDF parsing

**Files:**
- Create: `src/render/parse.py`
- Test: `tests/render/test_parse.py`

**Interfaces:**
- Consumes: `pdfminer.six`.
- Produces:
  - `TextBox(text: str, x0: float, y0: float, x1: float, y1: float, page: int)`
  - `ParsedPdf(boxes: tuple[TextBox, ...], page_height: float, page_width: float, size_bytes: int)`, with `.text` (boxes joined by `"\n"` in document order) and `.normalized_text` (casefolded, whitespace-collapsed).
  - `parse_pdf(path: str | Path) -> ParsedPdf`

- [ ] **Step 1: Write the failing test**

```python
# tests/render/test_parse.py
from pathlib import Path
import pytest
from src.render.parse import parse_pdf, ParsedPdf

FIXTURES = Path("tests/fixtures/render")
GOOD = FIXTURES / "good_single_column.pdf"

pytestmark = pytest.mark.skipif(
    not GOOD.exists(), reason="fixture not recorded yet (Task 4)"
)


def test_parse_returns_boxes_with_geometry():
    parsed = parse_pdf(GOOD)
    assert isinstance(parsed, ParsedPdf)
    assert parsed.boxes, "expected at least one text box"
    first = parsed.boxes[0]
    assert first.x1 > first.x0
    assert first.y1 > first.y0
    assert parsed.page_width > 0


def test_normalized_text_collapses_whitespace_and_case():
    parsed = parse_pdf(GOOD)
    assert "  " not in parsed.normalized_text
    assert parsed.normalized_text == parsed.normalized_text.casefold()


def test_size_bytes_matches_file():
    assert parse_pdf(GOOD).size_bytes == GOOD.stat().st_size
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/render/test_parse.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.render.parse'`
(Once the module exists these will *skip* until Task 4 records the fixture. That is intended.)

- [ ] **Step 3: Write the implementation**

```python
# src/render/parse.py
"""PDF text + geometry extraction. Pure over a file path; no rendering."""

import logging
from dataclasses import dataclass
from pathlib import Path

from pdfminer.high_level import extract_pages
from pdfminer.layout import LAParams, LTTextContainer

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TextBox:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    page: int


@dataclass(frozen=True)
class ParsedPdf:
    boxes: tuple[TextBox, ...]
    page_height: float
    page_width: float
    size_bytes: int

    @property
    def text(self) -> str:
        return "\n".join(box.text for box in self.boxes)

    @property
    def normalized_text(self) -> str:
        return " ".join(self.text.split()).casefold()


def parse_pdf(path: str | Path) -> ParsedPdf:
    """Extract text containers with bounding boxes, in document order."""
    path = Path(path)
    boxes: list[TextBox] = []
    page_height = 0.0
    page_width = 0.0

    for page_number, layout in enumerate(extract_pages(str(path), laparams=LAParams())):
        page_width = max(page_width, float(layout.width))
        page_height = max(page_height, float(layout.height))
        for element in layout:
            if not isinstance(element, LTTextContainer):
                continue
            text = element.get_text().strip()
            if not text:
                continue
            x0, y0, x1, y1 = element.bbox
            boxes.append(
                TextBox(
                    text=text,
                    x0=float(x0),
                    y0=float(y0),
                    x1=float(x1),
                    y1=float(y1),
                    page=page_number,
                )
            )

    logger.info("parsed %s: %d text boxes", path.name, len(boxes))
    return ParsedPdf(
        boxes=tuple(boxes),
        page_height=page_height,
        page_width=page_width,
        size_bytes=path.stat().st_size,
    )
```

- [ ] **Step 4: Confirm the module imports and tests skip rather than error**

Run: `.venv/bin/pytest tests/render/test_parse.py -v`
Expected: 3 skipped (fixture not yet recorded).

- [ ] **Step 5: Commit**

```bash
git add src/render/parse.py tests/render/test_parse.py
git commit -m "feat(m10): add pdfminer-based PDF parsing with geometry"
```

---

### Task 4: HUMAN CHECKPOINT — install TeX packages and record synthetic fixtures

**Step 1 cannot be completed by an agent. Stop and involve the user.**

**Files:**
- Read: `profile/Himanshu_Resume_New.tex` (the layout donor; `profile/` is gitignored)
- Create: `scripts/record_render_fixture.py`
- Create: `tests/fixtures/render/good_single_column.pdf` (binary, committed)
- Create: `tests/fixtures/render/bad_two_column.pdf` (binary, committed)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: the two fixture PDFs that Tasks 3, 5, and 6 assert against.

**Verified state as of 2026-07-31 — do not re-derive:**
Three sources exist in the gitignored `profile/`. All three preambles are byte-identical
(105 lines), so they are one layout with three content sets. Correspondence, established by
`pdftotext` word-overlap (89–91% vs ≤79% next-best):
`Himanshu_Resume_Gen.tex`→`Himanshu_Jain_Gen.pdf`, `Himanshu_Resume_cv.tex`→`Himanshu_Jain_cv.pdf`,
and `Himanshu_Resume_New.tex`→**`Himanshu_Jain.pdf`** (*not* the same-named
`Himanshu_Resume_New.pdf`). Use `Himanshu_Resume_New.tex` as the layout donor.
`pdflatex` is at `/Library/TeX/texbin/pdflatex`.

- [ ] **Step 1: Ask the user to install the three missing TeX packages**

This is a BasicTeX install; `titlesec`, `enumitem`, and `marvosym` are absent and **all three
sources fail to compile without them**. This needs the user's password — do not attempt it.

```bash
sudo tlmgr option repository https://ftp.math.utah.edu/pub/tex/historic/systems/texlive/2025/tlnet-final
sudo tlmgr install titlesec enumitem marvosym
```

The repository line is **required**: this machine runs TeX Live 2025 (BasicTeX, brew
cask `basictex` 2025.0308) while CTAN has moved to 2026, and `tlmgr` refuses
cross-release installs. Without it the install fails regardless of sudo. The three
packages total ~355 KB of runtime files. Alternative: `brew upgrade --cask basictex`
to move to 2026 first, then install from the default repo.

- [ ] **Step 1b: Delete the orphan `\end{itemize}`**

`profile/Himanshu_Resume_New.tex:217` closes a list that `\section{Technical Skills}` never
opens (that section is free-form text). It is a hard compile error: `! Undefined control
sequence` in `\enit@enditemize`. Everything else balances — Education, Experience, and both
Projects blocks each pair correctly, and the extra `\resumeSubHeadingListEnd` at line 167 is
commented out. Delete line 217 only; change nothing else.

Verified 2026-07-31: with that single line removed the donor compiles to a 1-page PDF whose
extracted text is a **100% word-overlap match** with `Himanshu_Jain.pdf` (313 shared terms,
0 present only in the original).

Note: M10 replaces the entire region between `\begin{document}` and `\end{document}` with
`$BODY` (Task 7 Step 1), so this defect disappears from generated output regardless. It must
still be fixed here because Task 4 compiles the donor as-is to record fixtures.

- [ ] **Step 2: Verify the template now compiles**

Run: `pdflatex -interaction=nonstopmode -halt-on-error -output-directory /tmp profile/Himanshu_Resume_New.tex`
Expected: exit 0, `/tmp/Himanshu_Resume_New.pdf` produced. If it still fails on a missing
`.sty`, install that package too and repeat — do not comment out packages to force a build.

- [ ] **Step 2b: Build the synthetic-identity variant**

**Fixtures must never carry the user's real contact details.** `profile/` is gitignored but
`tests/fixtures/` is tracked and `origin` is a public remote. Copy the donor to
`/tmp/fixture_src.tex` and replace the real name, phone, email, and LinkedIn/GitHub URLs
with `Test User`, `555-0100`, `test@example.com`, `https://example.com`. Verify before
rendering:

Run: `grep -cE "408-390-0164|himanshu\.jain@sjsu\.edu" /tmp/fixture_src.tex`
Expected: `0`

- [ ] **Step 3: Write the fixture recorder**

```python
# scripts/record_render_fixture.py
"""Record render fixtures once, offline. Committed output; never run in tests."""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

FIXTURE_DIR = Path("tests/fixtures/render")


def compile_tex(tex_path: Path, out_pdf: Path) -> None:
    if shutil.which("pdflatex") is None:
        sys.exit("pdflatex not found; cannot record a LaTeX fixture")
    workdir = out_pdf.parent
    workdir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["pdflatex", "-interaction=nonstopmode", "-output-directory", str(workdir),
         str(tex_path)],
        check=True,
        capture_output=True,
    )
    produced = workdir / (tex_path.stem + ".pdf")
    produced.replace(out_pdf)
    for junk in workdir.glob(tex_path.stem + ".*"):
        if junk.suffix in {".aux", ".log", ".out"}:
            junk.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tex", type=Path, help="source .tex to compile")
    parser.add_argument("name", help="fixture name, e.g. good_single_column")
    args = parser.parse_args()
    out = FIXTURE_DIR / f"{args.name}.pdf"
    compile_tex(args.tex, out)
    print(f"recorded {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Record the good fixture from the synthetic source**

Run: `.venv/bin/python scripts/record_render_fixture.py /tmp/fixture_src.tex good_single_column`

- [ ] **Step 5: Record the deliberately-bad fixture**

Copy `/tmp/fixture_src.tex` (the synthetic one, not the real profile) to `/tmp/bad_two_column.tex`, change `\documentclass[letterpaper,11pt]{article}` to `\documentclass[letterpaper,11pt,twocolumn]{article}`, then:
Run: `.venv/bin/python scripts/record_render_fixture.py /tmp/bad_two_column.tex bad_two_column`

- [ ] **Step 5b: Prove no real PII entered the fixtures**

Run: `pdftotext tests/fixtures/render/good_single_column.pdf - | grep -cE "408-390-0164|himanshu\.jain@sjsu\.edu"`
Expected: `0`. Repeat for `bad_two_column.pdf`. **If either returns non-zero, delete both fixtures and redo Step 2b** — do not commit them.

The bad fixture must be genuinely two-column — open it and confirm. A fixture that fails for an unrelated reason makes Task 6's acceptance criterion vacuous.

- [ ] **Step 6: Task 3's tests should now run and pass**

Run: `.venv/bin/pytest tests/render/test_parse.py -v`
Expected: 3 passed

- [ ] **Step 7: Commit**

```bash
git add scripts/record_render_fixture.py tests/fixtures/render/good_single_column.pdf tests/fixtures/render/bad_two_column.pdf
git commit -m "test(m10): record good and two-column render fixtures"
```

---

### Task 5: L7 content-survival checks

**Files:**
- Create: `src/render/l7.py`
- Test: `tests/render/test_l7_content.py`

**Interfaces:**
- Consumes: `RenderDoc` from `src.render.model`; `ParsedPdf`, `TextBox` from `src.render.parse`.
- Produces: `check_identity_survives`, `check_bullets_survive`, `check_skills_survive`, `check_charset`, `check_file_size` — each `(doc: RenderDoc, parsed: ParsedPdf) -> list[str]`. Also the private helper `_normalize(str) -> str`, reused by Task 6.

- [ ] **Step 1: Write the failing tests**

```python
# tests/render/test_l7_content.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/render/test_l7_content.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.render.l7'`

- [ ] **Step 3: Write the implementation**

```python
# src/render/l7.py
"""L7 parseability gate: does the PDF an ATS reads still say what we meant?

Every check returns a list of violation strings (empty == pass), matching the
convention in src/tailor/lint.py.
"""

import logging

from src.render.model import RenderDoc
from src.render.parse import ParsedPdf

logger = logging.getLogger(__name__)

_IDENTITY_FIELDS = ("name", "phone", "email", "location")


def _normalize(value: str) -> str:
    return " ".join(value.split()).casefold()


def check_identity_survives(doc: RenderDoc, parsed: ParsedPdf) -> list[str]:
    haystack = parsed.normalized_text
    violations = []
    for field in _IDENTITY_FIELDS:
        value = doc.identity.get(field, "")
        if not value:
            continue
        if _normalize(value) not in haystack:
            violations.append(
                f"L7 identity: {field} {value!r} did not survive PDF extraction"
            )
    return violations


def check_bullets_survive(doc: RenderDoc, parsed: ParsedPdf) -> list[str]:
    haystack = parsed.normalized_text
    return [
        f"L7 bullet: {bullet.bullet_id} did not survive PDF extraction"
        for bullet in doc.all_bullets()
        if _normalize(bullet.text) not in haystack
    ]


def check_skills_survive(doc: RenderDoc, parsed: ParsedPdf) -> list[str]:
    haystack = parsed.normalized_text
    return [
        f"L7 skills: term {term!r} did not survive PDF extraction"
        for term in doc.all_skill_terms()
        if _normalize(term) not in haystack
    ]


def check_charset(doc: RenderDoc, parsed: ParsedPdf) -> list[str]:
    forbidden = doc.ats.get("forbidden_chars", ())
    text = parsed.text
    return [
        f"L7 charset: forbidden character {char!r} present in rendered text"
        for char in forbidden
        if char in text
    ]


def check_file_size(doc: RenderDoc, parsed: ParsedPdf) -> list[str]:
    limit_mb = doc.ats.get("max_file_size_mb")
    if limit_mb is None:
        return []
    actual_mb = parsed.size_bytes / (1024 * 1024)
    if actual_mb > float(limit_mb):
        return [
            f"L7 size: PDF is {actual_mb:.2f} MB, exceeds ats.max_file_size_mb "
            f"of {limit_mb}"
        ]
    return []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/render/test_l7_content.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add src/render/l7.py tests/render/test_l7_content.py
git commit -m "feat(m10): add L7 content survival checks"
```

---

### Task 6: L7 layout checks (single column, contact in body, heading order)

**Files:**
- Modify: `src/render/l7.py`
- Test: `tests/render/test_l7_layout.py`

**Interfaces:**
- Consumes: `_normalize` and the Task 5 checks from `src.render.l7`.
- Produces: `check_single_column`, `check_contact_in_body`, `check_section_headings`, and the aggregator `run_l7(doc: RenderDoc, parsed: ParsedPdf) -> list[str]`.

**Algorithm notes for the implementer:**
- *Single column:* group boxes by page; sort each page's `x0` values and look for a gap larger than 25% of `page_width`. A gap only counts as a column split if **both** sides hold ≥ 25% of that page's boxes — that population floor is what stops a single indented block from tripping it.
- *Contact in body:* pdfminer reports PDF coordinates with y increasing **upward**, so the top of the page is high y. Assert the name appears in a box whose `y1` is **at or below** `page_height * 0.95` — inside the text frame rather than in a true header.
- *Heading order:* find each `section_order` name's first index in document order; indices must be strictly increasing.

- [ ] **Step 1: Write the failing tests**

```python
# tests/render/test_l7_layout.py
from pathlib import Path
import pytest
from src.render.l7 import (
    check_single_column, check_contact_in_body, check_section_headings, run_l7,
)
from src.render.model import RenderDoc
from src.render.parse import ParsedPdf, TextBox, parse_pdf

FIXTURES = Path("tests/fixtures/render")


def _doc(**kw) -> RenderDoc:
    base = dict(
        identity={"name": "Test User"},
        education=(), experience=(), projects=(),
        skills={},
        section_order=("Education", "Experience"),
        ats={"forbidden_chars": [], "max_file_size_mb": 2.5,
             "layout": {"columns": 1, "contact_in_body": True},
             "headings_whitelist": ["Education", "Experience", "Projects", "Skills"]},
    )
    base.update(kw)
    return RenderDoc(**base)


def _pdf(boxes) -> ParsedPdf:
    return ParsedPdf(boxes=tuple(boxes), page_height=792.0,
                     page_width=612.0, size_bytes=1000)


def test_single_column_layout_passes():
    boxes = [TextBox(text=f"line {i}", x0=50, y0=700 - i * 20,
                     x1=550, y1=715 - i * 20, page=0) for i in range(10)]
    assert check_single_column(_doc(), _pdf(boxes)) == []


def test_two_column_layout_is_reported():
    left = [TextBox(text=f"L{i}", x0=50, y0=700 - i * 20,
                    x1=280, y1=715 - i * 20, page=0) for i in range(6)]
    right = [TextBox(text=f"R{i}", x0=330, y0=700 - i * 20,
                     x1=560, y1=715 - i * 20, page=0) for i in range(6)]
    violations = check_single_column(_doc(), _pdf(left + right))
    assert len(violations) == 1
    assert "column" in violations[0].lower()


def test_single_indented_block_does_not_trip_column_check():
    body = [TextBox(text=f"line {i}", x0=50, y0=700 - i * 20,
                    x1=550, y1=715 - i * 20, page=0) for i in range(12)]
    indented = [TextBox(text="note", x0=330, y0=400, x1=560, y1=415, page=0)]
    assert check_single_column(_doc(), _pdf(body + indented)) == []


def test_column_check_is_skipped_when_policy_allows_columns():
    doc = _doc(ats={"layout": {"columns": 2}, "headings_whitelist": []})
    left = [TextBox(text=f"L{i}", x0=50, y0=700 - i * 20,
                    x1=280, y1=715 - i * 20, page=0) for i in range(6)]
    right = [TextBox(text=f"R{i}", x0=330, y0=700 - i * 20,
                     x1=560, y1=715 - i * 20, page=0) for i in range(6)]
    assert check_single_column(doc, _pdf(left + right)) == []


def test_contact_in_header_band_is_reported():
    boxes = [TextBox(text="Test User", x0=50, y0=780, x1=550, y1=790, page=0)]
    assert len(check_contact_in_body(_doc(), _pdf(boxes))) == 1


def test_contact_inside_body_passes():
    boxes = [TextBox(text="Test User", x0=50, y0=700, x1=550, y1=715, page=0)]
    assert check_contact_in_body(_doc(), _pdf(boxes)) == []


def test_out_of_order_headings_are_reported():
    boxes = [
        TextBox(text="Experience", x0=50, y0=700, x1=200, y1=715, page=0),
        TextBox(text="Education", x0=50, y0=600, x1=200, y1=615, page=0),
    ]
    assert len(check_section_headings(_doc(), _pdf(boxes))) == 1


def test_headings_in_order_pass():
    boxes = [
        TextBox(text="Education", x0=50, y0=700, x1=200, y1=715, page=0),
        TextBox(text="Experience", x0=50, y0=600, x1=200, y1=615, page=0),
    ]
    assert check_section_headings(_doc(), _pdf(boxes)) == []


def test_missing_heading_is_reported():
    boxes = [TextBox(text="Education", x0=50, y0=700, x1=200, y1=715, page=0)]
    violations = check_section_headings(_doc(), _pdf(boxes))
    assert any("Experience" in v for v in violations)


def test_run_l7_aggregates_all_checks():
    boxes = [TextBox(text="Education", x0=50, y0=700, x1=200, y1=715, page=0)]
    violations = run_l7(_doc(), _pdf(boxes))
    assert any("identity" in v for v in violations)
    assert any("Experience" in v for v in violations)


@pytest.mark.skipif(not (FIXTURES / "bad_two_column.pdf").exists(),
                    reason="fixture not recorded yet (Task 4)")
def test_two_column_fixture_fails_on_the_column_check_specifically():
    parsed = parse_pdf(FIXTURES / "bad_two_column.pdf")
    assert check_single_column(_doc(), parsed), (
        "the deliberately two-column fixture must trip the column check"
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/render/test_l7_layout.py -v`
Expected: FAIL with `ImportError: cannot import name 'check_single_column'`

- [ ] **Step 3: Append the implementation to `src/render/l7.py`**

```python
_COLUMN_SEPARATION_RATIO = 0.25
_COLUMN_POPULATION_FLOOR = 0.25
_HEADER_BAND_RATIO = 0.95


def check_single_column(doc: RenderDoc, parsed: ParsedPdf) -> list[str]:
    """Flag a bimodal x distribution: the classic ATS reading-order killer."""
    if doc.ats.get("layout", {}).get("columns", 1) != 1:
        return []

    pages: dict[int, list] = {}
    for box in parsed.boxes:
        pages.setdefault(box.page, []).append(box)

    threshold = parsed.page_width * _COLUMN_SEPARATION_RATIO
    violations = []
    for page, boxes in sorted(pages.items()):
        if len(boxes) < 4:
            continue
        starts = sorted(box.x0 for box in boxes)
        split_at = next(
            (i for i in range(1, len(starts))
             if starts[i] - starts[i - 1] > threshold),
            None,
        )
        if split_at is None:
            continue
        left, right = starts[:split_at], starts[split_at:]
        floor = len(boxes) * _COLUMN_POPULATION_FLOOR
        if len(left) >= floor and len(right) >= floor:
            violations.append(
                f"L7 layout: page {page} has two column clusters "
                f"(x~{left[0]:.0f} and x~{right[0]:.0f}); ats.layout.columns is 1"
            )
    return violations


def check_contact_in_body(doc: RenderDoc, parsed: ParsedPdf) -> list[str]:
    """Contact details in a true header/footer are dropped by Greenhouse."""
    if not doc.ats.get("layout", {}).get("contact_in_body", True):
        return []
    name = doc.identity.get("name", "")
    if not name:
        return []
    body_ceiling = parsed.page_height * _HEADER_BAND_RATIO
    for box in parsed.boxes:
        if _normalize(name) in _normalize(box.text) and box.y1 <= body_ceiling:
            return []
    return [
        "L7 layout: contact block sits in the header band, not the document body; "
        "ats.layout.contact_in_body is true"
    ]


def check_section_headings(doc: RenderDoc, parsed: ParsedPdf) -> list[str]:
    violations = []
    whitelist = doc.ats.get("headings_whitelist")
    if whitelist:
        illegal = [n for n in doc.section_order if n not in whitelist]
        if illegal:
            violations.append(
                f"L7 headings: section name(s) {illegal} not in ats.headings_whitelist"
            )

    positions = []
    for name in doc.section_order:
        target = _normalize(name)
        found = next(
            (i for i, box in enumerate(parsed.boxes) if target in _normalize(box.text)),
            None,
        )
        if found is None:
            violations.append(
                f"L7 headings: section {name!r} did not survive PDF extraction"
            )
        else:
            positions.append((name, found))

    for (prev_name, prev_idx), (name, idx) in zip(positions, positions[1:]):
        if idx <= prev_idx:
            violations.append(
                f"L7 headings: {name!r} appears before {prev_name!r} in reading "
                f"order; ATS section attribution will be wrong"
            )
    return violations


def run_l7(doc: RenderDoc, parsed: ParsedPdf) -> list[str]:
    """Aggregate every L7 check. Empty list == the PDF is deliverable."""
    violations: list[str] = []
    for check in (
        check_identity_survives,
        check_bullets_survive,
        check_skills_survive,
        check_charset,
        check_file_size,
        check_single_column,
        check_contact_in_body,
        check_section_headings,
    ):
        violations.extend(check(doc, parsed))
    logger.info("L7: %d violation(s)", len(violations))
    return violations
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/render/test_l7_layout.py -v`
Expected: 11 passed (the fixture test skips until Task 4 has run)

- [ ] **Step 5: Run the whole suite**

Run: `.venv/bin/pytest -q`
Expected: 785 + the new render tests, all passing.

- [ ] **Step 6: Commit**

```bash
git add src/render/l7.py tests/render/test_l7_layout.py
git commit -m "feat(m10): add L7 layout checks and run_l7 aggregator"
```

---

### Task 7: Arm (a) — LaTeX renderer

**Blocked on Task 4 Steps 1-2 (the missing TeX packages installed and the donor compiling). If the user declines the install, skip to Task 8 and record the block in Task 10.**

**Files:**
- Create: `src/render/latex.py`
- Test: `tests/render/test_latex.py`

**Interfaces:**
- Consumes: `RenderDoc` from `src.render.model`.
- Produces: `escape_latex(str) -> str`, the pure `emit_latex_body(doc: RenderDoc) -> str`, and `render_latex(doc: RenderDoc, template_path: Path, out_pdf: Path) -> Path`.

- [ ] **Step 1: Tokenize the template**

The macro contract is already verified (2026-07-31) — do not re-derive it:

```latex
\resumeSubheading{arg1}{arg2}{arg3}{arg4}   % slots SWAP by section:
%   Education:  {institution}{location}{degree}{dates}
%   Experience: {employer}{dates}{title}{location}
\resumeProjectHeading{\textbf{Name} $|$ \emph{tech} $|$ org}{dates}   % 2 args
\resumeItem{...}
\resumeSubHeadingListStart / End    \resumeItemListStart / End
```
Sections in the real template: `Education`, `Experience`, `Projects`, **`Technical Skills`**.
Skills are free-form inline text separated by `\textbar\`, not an itemize list.

Copy `profile/Himanshu_Resume_New.tex` to `profile/template.tex` (still gitignored) and
replace only its content region — everything between `\begin{document}` and
`\end{document}` — with `string.Template` placeholders `$BODY`, `$NAME`, `$PHONE`,
`$EMAIL`, `$LINKEDIN`, `$GITHUB`, `$LOCATION`. **Preserve all 105 preamble lines and every
`\newcommand` byte-for-byte.** The template is interview-tested; this code adapts to it,
never the reverse.

Note: the donor has an unbalanced-looking `\resumeItem` run in the Amdocs block (one item's
closing brace lands after two later items). It compiles, and regenerating the body from
`RenderDoc` fixes it structurally. Do not hand-patch the donor.

- [ ] **Step 2: Write the failing test for the pure emitter**

```python
# tests/render/test_latex.py
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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/pytest tests/render/test_latex.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.render.latex'`

- [ ] **Step 4: Write the implementation**

```python
# src/render/latex.py
"""Arm (a): emit the user's interview-tested LaTeX template from a RenderDoc."""

import logging
import shutil
import subprocess
from pathlib import Path
from string import Template

from src.render.model import RenderDoc

logger = logging.getLogger(__name__)

# Backslash must be replaced first, so iterate the source once per character.
_LATEX_ESCAPES = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def escape_latex(value: str) -> str:
    return "".join(_LATEX_ESCAPES.get(char, char) for char in value)


def _bullets(entry) -> list[str]:
    if not entry.bullets:
        return []
    return [
        r"\resumeItemListStart",
        *(rf"\resumeItem{{{escape_latex(b.text)}}}" for b in entry.bullets),
        r"\resumeItemListEnd",
    ]


def _education_block(entries) -> str:
    """\\resumeSubheading{institution}{location}{degree}{dates}"""
    lines = [r"\resumeSubHeadingListStart"]
    for entry in entries:
        lines.append(
            rf"\resumeSubheading{{{escape_latex(entry.heading)}}}"
            rf"{{{escape_latex(entry.location)}}}"
            rf"{{{escape_latex(entry.subheading)}}}"
            rf"{{{escape_latex(entry.date_range)}}}"
        )
        lines.extend(_bullets(entry))
    lines.append(r"\resumeSubHeadingListEnd")
    return "\n".join(lines)


def _experience_block(entries) -> str:
    """\\resumeSubheading{employer}{dates}{title}{location} -- slots 2 and 4 are
    swapped relative to Education. This asymmetry is the template's, not a bug."""
    lines = [r"\resumeSubHeadingListStart"]
    for entry in entries:
        lines.append(
            rf"\resumeSubheading{{{escape_latex(entry.heading)}}}"
            rf"{{{escape_latex(entry.date_range)}}}"
            rf"{{{escape_latex(entry.subheading)}}}"
            rf"{{{escape_latex(entry.location)}}}"
        )
        lines.extend(_bullets(entry))
    lines.append(r"\resumeSubHeadingListEnd")
    return "\n".join(lines)


def _projects_block(entries) -> str:
    r"""\resumeProjectHeading{\textbf{Name} $|$ \emph{tech} $|$ org}{dates}"""
    lines = [r"\resumeSubHeadingListStart"]
    for entry in entries:
        title = rf"\textbf{{{escape_latex(entry.heading)}}}"
        if entry.subheading:
            title += rf" $|$ \emph{{{escape_latex(entry.subheading)}}}"
        lines.append(
            rf"\resumeProjectHeading{{{title}}}{{{escape_latex(entry.date_range)}}}"
        )
        lines.extend(_bullets(entry))
    lines.append(r"\resumeSubHeadingListEnd")
    return "\n".join(lines)


def _skills_block(skills) -> str:
    r"""Free-form inline text, NOT a list:
    \textbf{Category}: term, term \textbar\ \textbf{Category}: ..."""
    chunks = [
        rf"\textbf{{{escape_latex(category)}}}: {escape_latex(', '.join(terms))}"
        for category, terms in skills.items()
    ]
    return "\\small\n" + " \\textbar\\ ".join(chunks)


def emit_latex_body(doc: RenderDoc) -> str:
    """Pure: RenderDoc -> LaTeX body. Bullet ids are stripped here (G0 boundary)."""
    groups = {
        "Education": lambda: _education_block(doc.education),
        "Experience": lambda: _experience_block(doc.experience),
        "Projects": lambda: _projects_block(doc.projects),
        "Skills": lambda: _skills_block(doc.skills),
        "Technical Skills": lambda: _skills_block(doc.skills),
    }
    parts = []
    for name in doc.section_order:
        builder = groups.get(name)
        if builder is None:
            continue
        parts.append(rf"\section{{{name}}}")
        parts.append(builder())
    return "\n".join(parts)


def render_latex(doc: RenderDoc, template_path: Path, out_pdf: Path) -> Path:
    """Substitute the body into the user's template and compile with pdflatex."""
    if shutil.which("pdflatex") is None:
        raise RuntimeError("pdflatex not found; arm (a) is un-runnable on this machine")

    template = Template(Path(template_path).read_text(encoding="utf-8"))
    source = template.safe_substitute(
        BODY=emit_latex_body(doc),
        NAME=escape_latex(doc.identity.get("name", "")),
        PHONE=escape_latex(doc.identity.get("phone", "")),
        EMAIL=escape_latex(doc.identity.get("email", "")),
        LINKEDIN=doc.identity.get("linkedin", ""),
        GITHUB=doc.identity.get("github", ""),
        LOCATION=escape_latex(doc.identity.get("location", "")),
    )

    out_pdf = Path(out_pdf)
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    tex_path = out_pdf.with_suffix(".tex")
    tex_path.write_text(source, encoding="utf-8")

    subprocess.run(
        ["pdflatex", "-interaction=nonstopmode", "-output-directory",
         str(out_pdf.parent), str(tex_path)],
        check=True,
        capture_output=True,
    )
    logger.info("rendered %s", out_pdf)
    return out_pdf
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/render/test_latex.py -v`
Expected: 4 passed

- [ ] **Step 6: Compile the emitted body end to end**

Unit tests on the emitter prove nothing about whether `pdflatex` accepts the output.

Run: `.venv/bin/python -c "
from pathlib import Path
from src.profile import load_profile
from src.render.mapping import build_render_doc
from src.render.latex import render_latex
p = load_profile('config/master_profile.yaml')
render_latex(build_render_doc(p, 'backend'), Path('profile/template.tex'), Path('/tmp/smoke/out.pdf'))
print('compiled')
"`
Expected: `compiled`. A LaTeX error here means an unescaped character reached the body — fix `escape_latex`, not the template.

- [ ] **Step 7: Commit**

```bash
git add src/render/latex.py tests/render/test_latex.py
git commit -m "feat(m10): add LaTeX renderer for bake-off arm a"
```

---

### Task 8: Arm (b) — RenderCV renderer

**Files:**
- Create: `src/render/rendercv.py`
- Test: `tests/render/test_rendercv.py`

**Interfaces:**
- Consumes: `RenderDoc` from `src.render.model`; `yaml` (already an approved dep).
- Produces: `emit_rendercv_yaml(doc: RenderDoc) -> dict` (pure) and `render_rendercv(doc: RenderDoc, out_pdf: Path) -> Path`.

- [ ] **Step 1: Install RenderCV and inspect its real schema**

Run: `.venv/bin/pip install rendercv && cd /tmp && /Users/himanshu_jain/aero/Resume_Finetune/job-pipeline/.venv/bin/rendercv new "Test User" && cat /tmp/Test_User_CV.yaml | head -60`
Read the generated YAML to learn the exact key names for `cv.sections`, `highlights`, and `design`. **Use the generated file's key names, not the ones guessed below.**

- [ ] **Step 2: Write the failing test**

```python
# tests/render/test_rendercv.py
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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/pytest tests/render/test_rendercv.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.render.rendercv'`

- [ ] **Step 4: Write the implementation**

```python
# src/render/rendercv.py
"""Arm (b): emit RenderCV YAML from a RenderDoc and invoke RenderCV."""

import logging
import subprocess
from pathlib import Path
from typing import Any

import yaml

from src.render.model import RenderDoc

logger = logging.getLogger(__name__)


def _entry_dicts(entries) -> list[dict[str, Any]]:
    out = []
    for entry in entries:
        item: dict[str, Any] = {
            "company": entry.heading,
            "position": entry.subheading,
        }
        if entry.date_range:
            item["date"] = entry.date_range
        if entry.location:
            item["location"] = entry.location
        if entry.bullets:
            item["highlights"] = [bullet.text for bullet in entry.bullets]
        out.append(item)
    return out


def emit_rendercv_yaml(doc: RenderDoc) -> dict[str, Any]:
    """Pure: RenderDoc -> RenderCV input dict. Bullet ids stripped (G0 boundary)."""
    sections: dict[str, Any] = {}
    for name in doc.section_order:
        if name == "Education":
            sections["education"] = _entry_dicts(doc.education)
        elif name == "Experience":
            sections["experience"] = _entry_dicts(doc.experience)
        elif name == "Projects":
            sections["projects"] = _entry_dicts(doc.projects)
        elif name == "Skills":
            sections["skills"] = [
                {"label": category, "details": ", ".join(terms)}
                for category, terms in doc.skills.items()
            ]

    return {
        "cv": {
            "name": doc.identity.get("name", ""),
            "email": doc.identity.get("email", ""),
            "phone": doc.identity.get("phone", ""),
            "location": doc.identity.get("location", ""),
            "social_networks": [
                {"network": "LinkedIn", "username": doc.identity.get("linkedin", "")},
                {"network": "GitHub", "username": doc.identity.get("github", "")},
            ],
            "sections": sections,
        },
        "design": {"theme": "engineeringresumes"},
    }


def render_rendercv(doc: RenderDoc, out_pdf: Path) -> Path:
    """Write RenderCV YAML and invoke the renderer."""
    out_pdf = Path(out_pdf)
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    yaml_path = out_pdf.with_suffix(".yaml")
    yaml_path.write_text(
        yaml.safe_dump(emit_rendercv_yaml(doc), sort_keys=False, allow_unicode=False),
        encoding="utf-8",
    )
    subprocess.run(
        ["rendercv", "render", str(yaml_path),
         "--output-folder-name", str(out_pdf.parent)],
        check=True,
        capture_output=True,
    )
    logger.info("rendered %s via RenderCV", out_pdf)
    return out_pdf
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/render/test_rendercv.py -v`
Expected: 4 passed

- [ ] **Step 6: Reconcile with RenderCV's real schema**

If Step 1's generated YAML uses different keys, fix `emit_rendercv_yaml` and the tests to match, then verify a real render: `.venv/bin/rendercv render <yaml>`. An emitter that passes unit tests but produces YAML RenderCV rejects is worthless.

- [ ] **Step 7: Commit**

```bash
git add src/render/rendercv.py tests/render/test_rendercv.py
git commit -m "feat(m10): add RenderCV renderer for bake-off arm b"
```

---

### Task 9: Tier B oracle (opt-in, never required)

**Files:**
- Create: `tests/render/test_l7_oracle.py`

**Interfaces:**
- Consumes: the fixtures from Task 4.
- Produces: nothing importable; a marked test only.

- [ ] **Step 1: Write the marked test**

```python
# tests/render/test_l7_oracle.py
"""Tier B: cross-check Tier A heuristics against a real resume parser.

Deselected by default (see the `oracle` marker in pyproject.toml). Requires Node.
A disagreement is a finding to investigate and record, not an automatic failure.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

FIXTURES = Path("tests/fixtures/render")
ORACLE = Path("tools/openresume-cli")

pytestmark = pytest.mark.oracle


@pytest.mark.skipif(shutil.which("node") is None, reason="Node not installed")
@pytest.mark.skipif(not ORACLE.exists(), reason="OpenResume CLI not vendored")
def test_oracle_agrees_two_column_fixture_loses_content():
    result = subprocess.run(
        ["node", str(ORACLE / "parse.js"), str(FIXTURES / "bad_two_column.pdf")],
        capture_output=True, text=True, check=True,
    )
    parsed = json.loads(result.stdout)
    assert not parsed.get("workExperiences"), (
        "Tier A flags this fixture as two-column; the oracle should also fail to "
        "extract structured experience from it. Agreement here is what justifies "
        "trusting Tier A in CI."
    )
```

- [ ] **Step 2: Verify it is deselected by default**

Run: `.venv/bin/pytest -q`
Expected: the oracle test does **not** appear in the count.

- [ ] **Step 3: Verify it can be selected explicitly**

Run: `.venv/bin/pytest -m oracle -v`
Expected: collected, then skipped (Node/CLI absent) — not errored.

- [ ] **Step 4: Commit**

```bash
git add tests/render/test_l7_oracle.py
git commit -m "test(m10): add opt-in Tier B parser oracle"
```

---

### Task 10: Bake-off script, HUMAN DECISION, and DECISIONS.md

**Files:**
- Create: `scripts/render_bakeoff.py`
- Modify: `docs/DECISIONS.md`
- Modify: `docs/ROADMAP.md` (M10 status under "Upgrades (M9–M12)")
- Modify: `docs/UPGRADE_PLAN.md` (M10 items 1–3)

**Interfaces:**
- Consumes: `build_render_doc`, `render_latex`, `render_rendercv`, `parse_pdf`, `run_l7`.
- Produces: a CLI that writes both PDFs and prints an L7 comparison.

- [ ] **Step 1: Write the bake-off script**

```python
# scripts/render_bakeoff.py
"""M10 bake-off: render both arms, run L7 on each, print a comparison.

Operator script. Visual acceptability is judged by the user, not by this script.
"""

import argparse
import logging
import sys
from pathlib import Path

from src.profile import load_profile
from src.render.l7 import run_l7
from src.render.mapping import build_render_doc
from src.render.parse import parse_pdf

OUT = Path("build/bakeoff")


def _try(label, fn, doc) -> None:
    try:
        pdf = fn()
    except Exception as exc:  # noqa: BLE001 - operator script reports, never crashes
        print(f"{label}: UN-RUNNABLE ({exc})")
        return
    violations = run_l7(doc, parse_pdf(pdf))
    status = "PASS" if not violations else f"FAIL ({len(violations)})"
    print(f"{label}: {pdf}  L7 {status}")
    for violation in violations:
        print(f"    - {violation}")


def main() -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", default="backend")
    parser.add_argument("--template", type=Path, default=None,
                        help="path to the user's .tex; omit to skip arm (a)")
    args = parser.parse_args()

    profile = load_profile("config/master_profile.yaml")
    doc = build_render_doc(profile, args.variant)
    OUT.mkdir(parents=True, exist_ok=True)

    if args.template is None:
        print("arm (a) LaTeX: SKIPPED (no --template supplied)")
    else:
        from src.render.latex import render_latex
        _try("arm (a) LaTeX",
             lambda: render_latex(doc, args.template, OUT / "latex.pdf"), doc)

    from src.render.rendercv import render_rendercv
    _try("arm (b) RenderCV",
         lambda: render_rendercv(doc, OUT / "rendercv.pdf"), doc)

    print("\nOpen both PDFs and judge visual acceptability. That call is the user's.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Add `build/` to .gitignore if absent**

Run: `grep -q "^build/" .gitignore || echo "build/" >> .gitignore`

- [ ] **Step 3: Run the bake-off**

Run: `.venv/bin/python -m scripts.render_bakeoff --variant backend --template profile/template.tex`

- [ ] **Step 4: HUMAN CHECKPOINT — present both PDFs to the user**

Stop here. Show the user `build/bakeoff/latex.pdf` and `build/bakeoff/rendercv.pdf` plus each arm's L7 result. **Do not pick a winner on the user's behalf** — criterion 1 in the spec is human judgment on an interview-tested artifact. Ask which one they want.

- [ ] **Step 5: Record the decision in `docs/DECISIONS.md`**

Append a dated entry containing: the winner and why; each arm's L7 result; whether the three missing TeX packages were installed; how the Task 0b conflicts were resolved; and — if LaTeX won — an explicit note that RenderCV is **not** adopted as a runtime dependency and should be uninstalled, with `CLAUDE.md`'s dependency list corrected to match.

- [ ] **Step 6: Re-record the good fixture from the winning renderer**

The committed fixture must come from the renderer actually in use, or L7 is regression-testing a renderer nobody ships.

Run: `.venv/bin/pytest tests/render -v`
Expected: all green, including the fixture-backed tests that previously skipped.

- [ ] **Step 7: Update the roadmap docs**

In `docs/ROADMAP.md`, update the M10 sentence under "Upgrades (M9–M12)" to record completion and the renderer decision. In `docs/UPGRADE_PLAN.md`, tick M10 items 1–3.

- [ ] **Step 8: Full suite and commit**

Run: `.venv/bin/pytest -q`
Expected: 785 + all new render tests passing, oracle deselected.

```bash
git add scripts/render_bakeoff.py docs/DECISIONS.md docs/ROADMAP.md docs/UPGRADE_PLAN.md .gitignore tests/fixtures/render/
git commit -m "feat(m10): add render bake-off script and record renderer decision"
```

---

## Post-completion notes

- **Do not push.** `origin/main` is a **public** GitHub repo (`hjain3004/Resume_Finetune`) and `config/master_profile.yaml` — phone, email, `known_gaps`, `interview_risk` — sits entirely in the unpushed set. Pushing publishes it. The local branch was 37 commits ahead as of 2026-07-31; that gap is deliberate until the user decides how to handle the PII.
- M10 does not start M8's render step. Wiring the tailor's structural output into `build_render_doc(tier_overrides=...)` and delivering an application PDF is M8 work, in a separate session.
- If `sudo tlmgr install titlesec enumitem marvosym` never happens, M10 still closes on arm (b) + the L7 gate, with the renderer decision explicitly deferred in `DECISIONS.md`. The gate is the durable deliverable.
