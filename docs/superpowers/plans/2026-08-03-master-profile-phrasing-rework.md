# master_profile Phrasing Rework + Emphasis Pipeline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut `config/master_profile.yaml` from 29 rendered bullets to 13 in the user's own voice, give the renderer the ability to bold spans, and add two mechanical guards so neither defect can recur.

**Architecture:** Bullet phrasings gain inline `**markup**`. A new pure parser splits that into plain text plus span offsets; the plain text flows to `RenderBullet.text` (so every existing L7 check keeps working untouched) and the offsets flow to the LaTeX and RenderCV emitters. A new `src/profile_lint.py` lints the profile for length, style, markup validity, and per-variant character budget. L7 gains a page-count assertion.

**Tech Stack:** Python 3.11+, PyYAML, pytest, pdfminer.six. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-03-master-profile-phrasing-rework-design.md`

## Global Constraints

- **Never `git push`.** `origin` is a public GitHub repo; `config/master_profile.yaml` holds real contact details and private notes that exist only in unpushed commits. Commit locally only.
- **No new dependencies.** Approved set only: requests, trafilatura, PyYAML, pytest, crawl4ai, pdfminer.six.
- **Tests never touch the network** and must never require a TeX installation.
- Use `.venv/bin/python` and `.venv/bin/pytest`. Bare `python3` lacks PyYAML.
- Python 3.11+, type hints everywhere, dataclasses at module boundaries, small pure functions, no `print` inside `src/`.
- **Never invent a claim.** Every rewritten bullet must stay supported by its existing `evidence` field. Fabrication is the one unrecoverable failure.
- **Preserve every bullet `id`.** The YAML field is `id` (not `bullet_id` — that name exists only on `RenderBullet`). Rewrite `phrasings`; never renumber.
- Blocked bullets (`claim_type` in `ownership_unresolved` / `needs_input`) may not enter any `bullet_order`.
- **Charset:** `ats.forbidden_chars` bans the tilde operator, multiplication sign, en dash, em dash, curly quotes, and right arrow. Use ASCII hyphens and straight quotes in all authored text.
- **Length is measured on PLAIN text**, after stripping `**` markers — that is what renders.
- Baseline: **785 tests passing** before this work starts.

---

### Task 1: Emphasis parser

**Files:**
- Create: `src/render/emphasis.py`
- Test: `tests/render/test_emphasis.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `parse_emphasis(raw: str) -> tuple[str, tuple[tuple[int, int], ...]]` returning `(plain_text, spans)` where each span is a `(start, end)` half-open offset pair into `plain_text`. Raises `EmphasisError(ValueError)` on unbalanced, empty, or nested markers.

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from src.render.emphasis import parse_emphasis, EmphasisError


def test_plain_text_has_no_spans():
    assert parse_emphasis("Built an event store.") == ("Built an event store.", ())


def test_single_span_offsets_locate_the_marked_text():
    plain, spans = parse_emphasis("Cut **p99 latency** by 40%.")
    assert plain == "Cut p99 latency by 40%."
    assert spans == ((4, 15),)
    assert plain[4:15] == "p99 latency"


def test_three_spans_are_all_located():
    plain, spans = parse_emphasis(
        "**Reduced footprint by 40%** and improved perf by 25% by building "
        "**data lifecycle management** with **event-driven archival**."
    )
    assert "**" not in plain
    assert [plain[s:e] for s, e in spans] == [
        "Reduced footprint by 40%",
        "data lifecycle management",
        "event-driven archival",
    ]


def test_repeated_substring_resolves_to_the_marked_occurrence():
    plain, spans = parse_emphasis("Kafka and **Kafka** again")
    assert spans == ((10, 15),)
    assert plain[10:15] == "Kafka"


def test_unbalanced_marker_raises():
    with pytest.raises(EmphasisError, match="unbalanced"):
        parse_emphasis("Cut **p99 latency by 40%.")


def test_empty_span_raises():
    with pytest.raises(EmphasisError, match="empty"):
        parse_emphasis("Cut **** latency.")


def test_nested_marker_raises():
    with pytest.raises(EmphasisError, match="nested"):
        parse_emphasis("Cut **p99 **latency** here** now.")


def test_single_asterisk_is_literal_text():
    plain, spans = parse_emphasis("Complexity is O(n*log n).")
    assert plain == "Complexity is O(n*log n)."
    assert spans == ()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/render/test_emphasis.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.render.emphasis'`

- [ ] **Step 3: Write the implementation**

```python
"""Inline emphasis markup. Pure: no I/O, no rendering.

`**text**` marks a span to emphasize. The parser returns the plain text (what
the PDF will contain, and therefore what L7 asserts against) plus offsets into
that plain text. Offsets rather than substrings so repeated text is unambiguous.
"""

import re

_MARKER = "**"
_MARKER_RE = re.compile(re.escape(_MARKER))


class EmphasisError(ValueError):
    """Raised when emphasis markup is unbalanced, empty, or nested."""


def parse_emphasis(raw: str) -> tuple[str, tuple[tuple[int, int], ...]]:
    """Split `**marked**` text into (plain_text, span offsets into plain_text)."""
    positions = [m.start() for m in _MARKER_RE.finditer(raw)]
    if len(positions) % 2:
        raise EmphasisError(f"unbalanced emphasis marker in {raw!r}")

    plain_parts: list[str] = []
    spans: list[tuple[int, int]] = []
    cursor = 0
    plain_len = 0

    for open_at, close_at in zip(positions[::2], positions[1::2]):
        body = raw[open_at + len(_MARKER):close_at]
        if not body:
            raise EmphasisError(f"empty emphasis span in {raw!r}")
        if _MARKER in body:
            raise EmphasisError(f"nested emphasis span in {raw!r}")

        before = raw[cursor:open_at]
        plain_parts.append(before)
        plain_len += len(before)

        spans.append((plain_len, plain_len + len(body)))
        plain_parts.append(body)
        plain_len += len(body)
        cursor = close_at + len(_MARKER)

    plain_parts.append(raw[cursor:])
    return "".join(plain_parts), tuple(spans)
```

Note: because `positions` are consumed in pairs, a nested `**` lands inside `body`
and is caught there. `test_nested_marker_raises` exercises exactly that path.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/render/test_emphasis.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add src/render/emphasis.py tests/render/test_emphasis.py
git commit -m "feat(m10): add inline emphasis markup parser"
```

---

### Task 2: Carry emphasis through the render IR

**Files:**
- Modify: `src/render/model.py` (the `RenderBullet` dataclass)
- Modify: `src/render/mapping.py:66-72` (the `selected` dict comprehension)
- Test: `tests/render/test_model.py`, `tests/render/test_mapping.py`

**Interfaces:**
- Consumes: `parse_emphasis` from Task 1.
- Produces: `RenderBullet(bullet_id: str, text: str, emphasis: tuple[tuple[int, int], ...] = ())`. `text` is always **plain** — markup-free — so `src/render/l7.py` needs no change at all.

- [ ] **Step 1: Write the failing tests**

Append to `tests/render/test_model.py`:

```python
def test_render_bullet_emphasis_defaults_to_empty():
    bullet = RenderBullet(bullet_id="b1", text="Built an event store.")
    assert bullet.emphasis == ()


def test_render_bullet_carries_emphasis_spans():
    bullet = RenderBullet(bullet_id="b1", text="Cut p99 by 40%.", emphasis=((4, 7),))
    assert bullet.text[4:7] == "p99"
```

Append to `tests/render/test_mapping.py`:

```python
def test_mapping_strips_markup_and_carries_spans():
    doc = build_render_doc(PROFILE, "backend")
    for bullet in doc.all_bullets():
        assert "**" not in bullet.text, f"{bullet.bullet_id} leaked markup into text"
        for start, end in bullet.emphasis:
            assert 0 <= start < end <= len(bullet.text)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/render/test_model.py tests/render/test_mapping.py -v`
Expected: FAIL — `TypeError: RenderBullet.__init__() got an unexpected keyword argument 'emphasis'`

- [ ] **Step 3: Write the implementation**

In `src/render/model.py`, replace the `RenderBullet` dataclass:

```python
@dataclass(frozen=True)
class RenderBullet:
    """One bullet. `bullet_id` carries G0 traceability to the renderer boundary.

    `text` is always plain: emphasis markup is stripped at mapping time so L7's
    survival checks compare against exactly what the PDF will contain.
    `emphasis` holds (start, end) half-open offsets into `text`.
    """

    bullet_id: str
    text: str
    emphasis: tuple[tuple[int, int], ...] = ()
```

In `src/render/mapping.py`, add the import:

```python
from src.render.emphasis import parse_emphasis
```

and replace the `selected` comprehension (currently lines 66-72) with:

```python
    def _build_bullet(bullet) -> RenderBullet:
        plain, spans = parse_emphasis(_resolve_text(bullet, overrides.get(bullet.id)))
        return RenderBullet(bullet_id=bullet.id, text=plain, emphasis=spans)

    selected = {bullet.id: _build_bullet(bullet) for _, bullet in ordered}
```

- [ ] **Step 4: Run the full suite to verify nothing regressed**

Run: `.venv/bin/pytest -q`
Expected: 785 baseline plus 3 new tests, all passing. The `= ()` default keeps all six existing `RenderBullet(...)` construction sites valid.

- [ ] **Step 5: Commit**

```bash
git add src/render/model.py src/render/mapping.py tests/render/test_model.py tests/render/test_mapping.py
git commit -m "feat(m10): carry emphasis spans through the render IR"
```

---

### Task 3: Bold in the LaTeX emitter

**Files:**
- Modify: `src/render/latex.py:32-40` (the `_bullets` helper)
- Test: `tests/render/test_latex.py`

**Interfaces:**
- Consumes: `RenderBullet.emphasis` from Task 2, `escape_latex` from `src/render/latex.py`.
- Produces: `_emphasized(bullet) -> str` — a fully escaped LaTeX string with `\textbf{}` around emphasized spans.

**The trap:** escaping must happen **per segment**, before the `\textbf{` braces are added. Escaping afterwards would turn `\textbf{x}` into `\textbackslash{}textbf\{x\}`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/render/test_latex.py`:

```python
from src.render.emphasis import parse_emphasis
from src.render.latex import _emphasized


def _bullet(raw: str) -> RenderBullet:
    plain, spans = parse_emphasis(raw)
    return RenderBullet(bullet_id="b1", text=plain, emphasis=spans)


def test_plain_bullet_emits_no_textbf():
    assert _emphasized(_bullet("Cut p99 by 40 percent.")) == "Cut p99 by 40 percent."


def test_emphasized_span_is_wrapped_in_textbf():
    assert _emphasized(_bullet("Cut **p99 latency** here.")) == (
        r"Cut \textbf{p99 latency} here."
    )


def test_latex_special_inside_an_emphasized_span_is_escaped():
    assert _emphasized(_bullet("**Cut p99 by 40%** now.")) == (
        r"\textbf{Cut p99 by 40\%} now."
    )


def test_latex_special_outside_an_emphasized_span_is_escaped():
    assert _emphasized(_bullet("Cut **p99** by 40% & held.")) == (
        r"Cut \textbf{p99} by 40\% \& held."
    )


def test_span_at_string_start_and_end():
    assert _emphasized(_bullet("**alpha** mid **omega**")) == (
        r"\textbf{alpha} mid \textbf{omega}"
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/render/test_latex.py -v`
Expected: FAIL — `ImportError: cannot import name '_emphasized'`

- [ ] **Step 3: Write the implementation**

In `src/render/latex.py`, add `_emphasized` above `_bullets` and change `_bullets` to call it:

```python
def _emphasized(bullet) -> str:
    """Escape per segment, then wrap emphasized segments in \\textbf{}.

    Escaping must precede brace insertion, or escape_latex would escape the
    \\textbf braces themselves.
    """
    if not bullet.emphasis:
        return escape_latex(bullet.text)

    parts: list[str] = []
    cursor = 0
    for start, end in bullet.emphasis:
        parts.append(escape_latex(bullet.text[cursor:start]))
        parts.append(rf"\textbf{{{escape_latex(bullet.text[start:end])}}}")
        cursor = end
    parts.append(escape_latex(bullet.text[cursor:]))
    return "".join(parts)


def _bullets(entry) -> list[str]:
    if not entry.bullets:
        return []
    return [
        r"\resumeItemListStart",
        *(rf"\resumeItem{{{_emphasized(b)}}}" for b in entry.bullets),
        r"\resumeItemListEnd",
    ]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/render/test_latex.py -v`
Expected: all passing, including the pre-existing LaTeX tests.

- [ ] **Step 5: Commit**

```bash
git add src/render/latex.py tests/render/test_latex.py
git commit -m "feat(m10): emit textbf for emphasized spans in the LaTeX arm"
```

---

### Task 4: Bold in the RenderCV emitter

**Files:**
- Modify: `src/render/rendercv.py:26-27` (the `highlights` assignment in `_entry_dicts`)
- Test: `tests/render/test_rendercv.py`

**Interfaces:**
- Consumes: `RenderBullet.emphasis` from Task 2.
- Produces: `_markdown(bullet) -> str` — the bullet text with `**` markers reinserted around emphasized spans. RenderCV highlights are markdown, so `**` is native.

- [ ] **Step 1: Write the failing tests**

Append to `tests/render/test_rendercv.py`:

```python
from src.render.emphasis import parse_emphasis
from src.render.rendercv import _markdown


def test_markdown_round_trips_emphasis():
    raw = "Cut **p99 latency** by 40%."
    plain, spans = parse_emphasis(raw)
    bullet = RenderBullet(bullet_id="b1", text=plain, emphasis=spans)
    assert _markdown(bullet) == raw


def test_markdown_leaves_plain_text_untouched():
    bullet = RenderBullet(bullet_id="b1", text="Cut p99 by 40%.")
    assert _markdown(bullet) == "Cut p99 by 40%."
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/render/test_rendercv.py -v`
Expected: FAIL — `ImportError: cannot import name '_markdown'`

- [ ] **Step 3: Write the implementation**

In `src/render/rendercv.py`, add `_markdown` above `_entry_dicts`:

```python
def _markdown(bullet) -> str:
    """Reinsert ** markers. RenderCV highlights are markdown."""
    if not bullet.emphasis:
        return bullet.text
    parts: list[str] = []
    cursor = 0
    for start, end in bullet.emphasis:
        parts.append(bullet.text[cursor:start])
        parts.append(f"**{bullet.text[start:end]}**")
        cursor = end
    parts.append(bullet.text[cursor:])
    return "".join(parts)
```

Then change line 27 from `item["highlights"] = [bullet.text for bullet in entry.bullets]` to:

```python
            item["highlights"] = [_markdown(bullet) for bullet in entry.bullets]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/render/test_rendercv.py -v`
Expected: all passing.

- [ ] **Step 5: Commit**

```bash
git add src/render/rendercv.py tests/render/test_rendercv.py
git commit -m "feat(m10): emit markdown emphasis in the RenderCV arm"
```

---

### Task 5: L7 page-count guard

**Files:**
- Modify: `src/render/parse.py` (add a `page_count` property to `ParsedPdf`)
- Modify: `src/render/l7.py` (add `check_page_count`, register it in `run_l7`)
- Modify: `config/master_profile.yaml` (`ats.layout.max_pages: 1`)
- Test: `tests/render/test_l7_layout.py`

**Interfaces:**
- Consumes: `ParsedPdf`, `RenderDoc`.
- Produces: `ParsedPdf.page_count -> int`; `check_page_count(doc, parsed) -> list[str]`.

**Note:** `ParsedPdf` has **no** page-count field today — it is derivable from `TextBox.page`. Tests build `ParsedPdf` directly from `TextBox` tuples (see the existing `_pdf()` helper in `tests/render/test_l7_layout.py`), so no PDF fixture and no TeX are needed.

- [ ] **Step 1: Write the failing tests**

Append to `tests/render/test_l7_layout.py` (the `_doc` and `_pdf` helpers already exist there):

```python
from src.render.l7 import check_page_count


def _doc_with_max_pages(max_pages):
    layout = {"columns": 1, "contact_in_body": True}
    if max_pages is not None:
        layout["max_pages"] = max_pages
    return _doc(ats={"forbidden_chars": [], "max_file_size_mb": 2.5,
                     "layout": layout,
                     "headings_whitelist": ["Education", "Experience"]})


def _boxes_on_pages(pages):
    return [TextBox(text=f"line {p}", x0=50, y0=700, x1=550, y1=715, page=p)
            for p in pages]


def test_page_count_property_counts_distinct_pages():
    assert _pdf(_boxes_on_pages([0, 0, 1])).page_count == 2
    assert _pdf(_boxes_on_pages([0])).page_count == 1
    assert _pdf([]).page_count == 0


def test_single_page_passes_the_page_count_check():
    assert check_page_count(_doc_with_max_pages(1), _pdf(_boxes_on_pages([0]))) == []


def test_two_page_pdf_is_reported():
    violations = check_page_count(_doc_with_max_pages(1), _pdf(_boxes_on_pages([0, 1])))
    assert len(violations) == 1
    assert "2 page" in violations[0]


def test_page_count_check_is_skipped_when_max_pages_is_absent():
    assert check_page_count(_doc_with_max_pages(None), _pdf(_boxes_on_pages([0, 1]))) == []


def test_run_l7_includes_the_page_count_check():
    violations = run_l7(_doc_with_max_pages(1), _pdf(_boxes_on_pages([0, 1])))
    assert any("page" in v and "exceeds" in v for v in violations)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/render/test_l7_layout.py -v`
Expected: FAIL — `ImportError: cannot import name 'check_page_count'`

- [ ] **Step 3: Write the implementation**

In `src/render/parse.py`, add to the `ParsedPdf` dataclass alongside the existing `text` / `normalized_text` properties:

```python
    @property
    def page_count(self) -> int:
        return max((box.page for box in self.boxes), default=-1) + 1
```

In `src/render/l7.py`, add after `check_file_size`:

```python
def check_page_count(doc: RenderDoc, parsed: ParsedPdf) -> list[str]:
    """One page is the rule the whole content budget exists to satisfy."""
    limit = doc.ats.get("layout", {}).get("max_pages")
    if limit is None:
        return []
    if parsed.page_count > int(limit):
        return [
            f"L7 layout: PDF is {parsed.page_count} page(s), exceeds "
            f"ats.layout.max_pages of {limit}"
        ]
    return []
```

Then add `check_page_count,` to the tuple inside `run_l7`, after `check_file_size,`.

In `config/master_profile.yaml`, add `max_pages: 1` under `ats.layout` (which currently holds `columns`, `contact_in_body`, `tables`, `text_boxes`, `graphics`).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/render/ -q && .venv/bin/python -m scripts.validate_profile`
Expected: tests pass; validator still prints OK.

- [ ] **Step 5: Commit**

```bash
git add src/render/parse.py src/render/l7.py config/master_profile.yaml tests/render/test_l7_layout.py
git commit -m "feat(m10): assert one-page output in L7"
```

---

### Task 6: Profile phrasing lint

**Files:**
- Create: `src/profile_lint.py`
- Create: `tests/fixtures/profile_lint_minimal.yaml`
- Modify: `scripts/validate_profile.py`
- Test: `tests/test_profile_lint.py`

**Interfaces:**
- Consumes: `MasterProfile`, `Bullet`, `Phrasings` from `src/profile.py`; `parse_emphasis` / `EmphasisError` from Task 1.
- Produces: `lint_profile(profile: MasterProfile) -> list[str]` — violation strings, empty meaning clean. Matches the convention in `src/render/l7.py` and `src/tailor/lint.py`. Module constants `MEDIUM_MAX = 400`, `SHORT_MAX = 200`, `MAX_SPANS = 3`, `VARIANT_BUDGET = 3800`.

**Why a separate module, not `load_profile`:** style opinions must never make the profile schema-invalid for the tailor, and folding them in would break the synthetic fixtures in `tests/test_profile.py`.

**Data shapes you need:** `Phrasings(short: str, medium: str | None = None, long: str | None = None)`. `Bullet(id, claim_type, priority, phrasings, evidence, keywords_hit, defense, interview_risk)`. Bullets live on `profile.projects[*].bullets` and `profile.experience[*].bullets`. `profile.base_variants[name].bullet_order` is a tuple of bullet ids.

**Short-only bullets exist** (`pc_b06`, `sepsis_b9`, `sepsis_b11`, `frd_b7` have `medium: None`). Every rule must skip a missing `medium` rather than crash.

- [ ] **Step 1: Create the test fixture**

Read the minimal valid-profile YAML already embedded in `tests/test_profile.py` (around line 70, the one containing `bullet_order: [exp_b1, proj_b1]`) — that is the authoritative shape. Copy it to `tests/fixtures/profile_lint_minimal.yaml` with these changes:

- **Synthetic identity only** — no real name, phone, or email in the fixture.
- Give the ordered experience bullet `exp_b1` a `medium` of exactly `MEDIUM_SENTINEL` and a `short` of exactly `SHORT_SENTINEL`.
- Add one extra bullet outside `bullet_order` that has `short` only and no `medium`, to exercise the short-only path.

- [ ] **Step 2: Write the failing tests**

```python
import pytest
from src.profile import load_profile
from src.profile_lint import lint_profile, MEDIUM_MAX, SHORT_MAX

FIXTURE = "tests/fixtures/profile_lint_minimal.yaml"
_CLEAN_MEDIUM = "Built **an event store** on PostgreSQL for the ordering domain."
_CLEAN_SHORT = "Built an event store on PostgreSQL."


def _profile(tmp_path, medium=_CLEAN_MEDIUM, short=_CLEAN_SHORT):
    text = open(FIXTURE).read()
    text = text.replace("MEDIUM_SENTINEL", medium).replace("SHORT_SENTINEL", short)
    path = tmp_path / "p.yaml"
    path.write_text(text)
    return load_profile(str(path))


def test_clean_fixture_passes(tmp_path):
    assert lint_profile(_profile(tmp_path)) == []


def test_overlong_medium_is_reported(tmp_path):
    violations = lint_profile(_profile(tmp_path, medium="Built **x** " + "y" * MEDIUM_MAX))
    assert any("medium" in v and "exceeds" in v for v in violations)


def test_overlong_short_is_reported(tmp_path):
    violations = lint_profile(_profile(tmp_path, short="Built " + "y" * SHORT_MAX))
    assert any("short" in v and "exceeds" in v for v in violations)


def test_gerund_opening_is_reported(tmp_path):
    violations = lint_profile(_profile(tmp_path, medium="Building **a thing** here."))
    assert any("gerund" in v for v in violations)


def test_banned_word_is_reported(tmp_path):
    violations = lint_profile(_profile(tmp_path, medium="Built **a robust thing** here."))
    assert any("banned" in v and "robust" in v for v in violations)


def test_unbalanced_markup_is_reported(tmp_path):
    violations = lint_profile(_profile(tmp_path, medium="Built **a thing here."))
    assert any("markup" in v for v in violations)


def test_more_than_three_spans_is_reported(tmp_path):
    medium = "Built **a** and **b** and **c** and **d** here."
    violations = lint_profile(_profile(tmp_path, medium=medium))
    assert any("spans" in v for v in violations)


def test_ordered_bullet_without_emphasis_is_reported(tmp_path):
    violations = lint_profile(_profile(tmp_path, medium="Built a thing here."))
    assert any("at least one" in v for v in violations)


def test_short_only_bullet_does_not_crash(tmp_path):
    assert lint_profile(_profile(tmp_path)) == []


def test_variant_over_budget_is_reported(tmp_path):
    # One ordered bullet at the medium ceiling cannot breach a 3800-char budget,
    # so drive the budget rule directly rather than through the fixture.
    profile = _profile(tmp_path)
    monkey_budget = 10
    import src.profile_lint as lint_mod

    original = lint_mod.VARIANT_BUDGET
    lint_mod.VARIANT_BUDGET = monkey_budget
    try:
        violations = lint_profile(profile)
    finally:
        lint_mod.VARIANT_BUDGET = original
    assert any("budget" in v and "base_variants" in v for v in violations)
```

Note: the budget rule reads `VARIANT_BUDGET` at call time (module-level lookup inside
`lint_profile`), which is what makes this override work. Keep it that way — do not
capture the constant as a default argument.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_profile_lint.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.profile_lint'`

- [ ] **Step 4: Write the implementation**

```python
"""Style lint for config/master_profile.yaml.

Separate from load_profile on purpose: a style violation must never make the
profile schema-invalid for the tailor. Thresholds are calibrated to the user's
own one-page resumes (median ~275 chars, max 395), not to L4's 2-line rule.

Every check returns violation strings; empty means clean, matching
src/render/l7.py and src/tailor/lint.py.
"""

import logging
from pathlib import Path

from src.profile import Bullet, MasterProfile
from src.render.emphasis import EmphasisError, parse_emphasis

logger = logging.getLogger(__name__)

MEDIUM_MAX = 400
SHORT_MAX = 200
MAX_SPANS = 3
VARIANT_BUDGET = 3800
_BANNED_WORDS_PATH = "config/banned_words.txt"


def _banned_words() -> tuple[str, ...]:
    text = Path(_BANNED_WORDS_PATH).read_text()
    return tuple(line.strip().casefold() for line in text.splitlines() if line.strip())


def _plain(raw: str) -> str:
    return parse_emphasis(raw)[0]


def _check_phrasing(bullet_id: str, tier: str, raw: str, limit: int,
                    banned: tuple[str, ...]) -> list[str]:
    try:
        plain, spans = parse_emphasis(raw)
    except EmphasisError as exc:
        return [f"lint {bullet_id}.{tier}: invalid markup: {exc}"]

    violations: list[str] = []
    if len(plain) > limit:
        violations.append(
            f"lint {bullet_id}.{tier}: {len(plain)} chars exceeds limit of {limit}"
        )
    if len(spans) > MAX_SPANS:
        violations.append(
            f"lint {bullet_id}.{tier}: {len(spans)} emphasis spans exceeds {MAX_SPANS}"
        )
    words = plain.split()
    if words and words[0].casefold().endswith("ing"):
        violations.append(
            f"lint {bullet_id}.{tier}: opens with gerund {words[0]!r}; use past tense"
        )
    folded = plain.casefold()
    violations.extend(
        f"lint {bullet_id}.{tier}: contains banned word {word!r}"
        for word in banned
        if word in folded
    )
    return violations


def _all_bullets(profile: MasterProfile) -> tuple[Bullet, ...]:
    return tuple(
        bullet
        for source in (*profile.projects, *profile.experience)
        for bullet in source.bullets
    )


def lint_profile(profile: MasterProfile) -> list[str]:
    """Every style violation in the profile. Empty list == clean."""
    banned = _banned_words()
    bullets = _all_bullets(profile)
    ordered_ids = {
        bullet_id
        for variant in profile.base_variants.values()
        for bullet_id in variant.bullet_order
    }

    violations: list[str] = []
    for bullet in bullets:
        violations.extend(
            _check_phrasing(bullet.id, "short", bullet.phrasings.short,
                            SHORT_MAX, banned)
        )
        if bullet.phrasings.long is not None:
            violations.extend(
                _check_phrasing(bullet.id, "long", bullet.phrasings.long,
                                MEDIUM_MAX * 2, banned)
            )
        if bullet.phrasings.medium is None:
            continue

        violations.extend(
            _check_phrasing(bullet.id, "medium", bullet.phrasings.medium,
                            MEDIUM_MAX, banned)
        )
        if bullet.id in ordered_ids:
            try:
                _, spans = parse_emphasis(bullet.phrasings.medium)
            except EmphasisError:
                spans = ()
            if not spans:
                violations.append(
                    f"lint {bullet.id}.medium: rendered bullet needs at least "
                    f"one emphasis span"
                )

    index = {bullet.id: bullet for bullet in bullets}
    for name, variant in profile.base_variants.items():
        total = 0
        for bullet_id in variant.bullet_order:
            bullet = index.get(bullet_id)
            if bullet is None or bullet.phrasings.medium is None:
                continue
            try:
                total += len(_plain(bullet.phrasings.medium))
            except EmphasisError:
                total += len(bullet.phrasings.medium)
        if total > VARIANT_BUDGET:
            violations.append(
                f"lint base_variants.{name}: {total} chars of bullet text exceeds "
                f"the one-page budget of {VARIANT_BUDGET}"
            )

    logger.info("profile lint: %d violation(s)", len(violations))
    return violations
```

- [ ] **Step 5: Wire it into the validator**

In `scripts/validate_profile.py`, add `from src.profile_lint import lint_profile` to the imports and, after the existing `print(...)` of the OK line and before `return 0`:

```python
    violations = lint_profile(profile)
    if violations:
        for violation in violations:
            print(violation, file=sys.stderr)
        print(f"LINT FAILED: {len(violations)} violation(s)", file=sys.stderr)
        return 1
    print("LINT OK")
    return 0
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_profile_lint.py -v`
Expected: 10 passed.

Then run: `.venv/bin/python -m scripts.validate_profile`
Expected: **exits 1 with LINT FAILED** — violations on `int_b7` (medium 431), `int_b8` (medium 481), `short` over 200 on `int_b1`, `sepsis_b9`, `sepsis_b11`, `frd_b7`, plus a missing-emphasis violation on every ordered bullet and a variant budget violation. This is correct; Tasks 7-9 fix the content.

- [ ] **Step 7: Commit**

```bash
git add src/profile_lint.py scripts/validate_profile.py tests/test_profile_lint.py tests/fixtures/profile_lint_minimal.yaml
git commit -m "feat(m8): add phrasing lint for master_profile"
```

---

### Task 7: Rewrite the internship bullets

**Files:**
- Modify: `config/master_profile.yaml` (`experience[bank_integration_internship].bullets`)

**Interfaces:**
- Consumes: nothing in code.
- Produces: rewritten `phrasings` on `int_b1`, `int_b2`, `int_b3`; trimmed `short` on `int_b1`; trimmed `medium` on `int_b7` and `int_b8`.

Eight bullets become three in `bullet_order`. `int_b4` and `int_b8` are **merged into** `int_b2` and `int_b3`; their own entries stay in the profile untouched apart from lint fixes, and remain available to the M8 tailor.

- [ ] **Step 1: Replace `int_b1.phrasings.medium`**

```yaml
      medium: "Built the **anti-corruption layer** between a commercial bank's core systems and four external providers - telecom messaging, real-time interbank transfers, national identity verification, and AML sanctions screening - as **four asynchronous Python microservices (FastAPI, SQLAlchemy 2.0, PostgreSQL)** on one standardized adapter architecture."
```

- [ ] **Step 2: Replace `int_b1.phrasings.short`** (currently 214 chars, over the 200 limit)

```yaml
      short: "Built the anti-corruption layer between a commercial bank and four external providers as four asynchronous Python microservices."
```

- [ ] **Step 3: Replace `int_b2.phrasings.medium`** — merges `int_b2` (idempotency) with `int_b4` (the transfer adapter it runs on)

```yaml
      medium: "Engineered **exactly-once semantics on the money-movement path** using INSERT-first idempotency reservation with atomic ON CONFLICT claims and SHA-256 payload fingerprinting, proven under an **8-way parallel duplicate harness** to yield exactly one vendor call; built the underlying real-time interbank transfer adapter across 8 transaction types with three-layer settlement validation."
```

Both halves are supported by existing evidence: `int_b2.evidence` covers the idempotency state machine and the 8-way harness; `int_b4.evidence` covers the 8 request types and the three-layer success condition. **No new claim is introduced.**

- [ ] **Step 4: Replace `int_b3.phrasings.medium`** — merges `int_b3` (fail-closed AML) with `int_b8` (security hardening)

```yaml
      medium: "Designed a **fail-closed AML sanctions screening gateway** that returns an explicit error rather than a false clear on any backend fault, timeout, or unparseable response, served over both REST/JSON and the legacy SOAP/XML contract from shared orchestration; hardened all four services with **credential isolation, recursive PII redaction, and XML-injection resistance**."
```

- [ ] **Step 5: Replace `int_b3.phrasings.short`**

```yaml
      short: "Designed a fail-closed AML sanctions screening gateway serving REST and legacy SOAP consumers, with credential isolation and PII redaction."
```

- [ ] **Step 6: Trim the two demoted over-limit bullets**

`int_b7.phrasings.medium` is 431 chars and `int_b8.phrasings.medium` is 481 — both over the 400 limit. Cut each to under 400 by dropping trailing parenthetical detail, keeping the leading claim and every named technology intact. Do **not** delete either bullet; they stay available to the tailor.

- [ ] **Step 7: Verify the profile still loads**

Run: `.venv/bin/python -m scripts.validate_profile`
Expected: still LINT FAILED (Amdocs and projects are not done yet), but no `int_*` length or markup violations should remain.

- [ ] **Step 8: Commit**

```bash
git add config/master_profile.yaml
git commit -m "content(m8): collapse internship bullets to three and add emphasis"
```

---

### Task 8: Rewrite the Amdocs bullets and reinstate the metrics

**Files:**
- Modify: `config/master_profile.yaml` (`experience[amdocs_software_developer]`)
- Modify: `docs/DECISIONS.md`

**Interfaces:**
- Consumes: nothing in code.
- Produces: new bullet `am_b00_order_management_domain`; rewritten `phrasings` on `am_b01`-`am_b05`; `priority: 1` on `am_b03`/`am_b04`/`am_b05`; `claim_type: estimated` on `am_b05`; five `metric_ledger` entries flipped to `renderable: true`.

- [ ] **Step 1: Flip the five metric_ledger entries to renderable**

In `amdocs_software_developer.metric_ledger`, set `renderable: true` on `purge_footprint`, `purge_query_gain`, `qa_effort_reduction`, `defect_reduction`, and `resolution_time_gain`. Leave `provenance: estimated` unchanged — legal because `ESTIMATED` is **not** in `NON_RENDERABLE_PROVENANCES` (only `UNSOURCED`, `CONTRADICTED`, `NONE` are). Add to each:

```yaml
      note: "Reinstated 2026-08-03 by user decision; present on the interview-tested resume."
```

- [ ] **Step 2: Rewrite the `am_gap_estimated_metrics` known_gap**

Its current `fix` reads "Keep it that way" — now factually stale. Replace `detail` and `fix`:

```yaml
      detail: "Five figures (~40%, ~25%, ~50%, ~40%, ~60%) are two-year-old reconstructions with no reproducible measurement behind them. The user reinstated all five on 2026-08-03: they appear on the interview-tested resume and describe work the user personally did."
      fix: "Rehearse the defense string for each verbatim before any interview. If pressed on methodology, say plainly that these are reconstructed estimates from the period, not instrumented measurements."
```

- [ ] **Step 3: Add the new `am_b00` bullet** as the first entry in `amdocs_software_developer.bullets`

```yaml
    - id: am_b00_order_management_domain
      claim_type: verified
      priority: 1
      phrasings:
        medium: "Engineered and maintained **Java and Spring Boot microservices for the Order Management domain** (Catalog, Shopping Cart, Proposal and Agreement), with a **Jenkins-driven CI/CD pipeline** automating builds, tests, and deployments across OpenShift environments."
        short: "Engineered Java and Spring Boot microservices for the Order Management domain, deployed through Jenkins CI/CD pipelines to OpenShift."
      evidence:
        - "amdocs_software_developer.scope_line names the Order Management domain (Catalog, Shopping Cart, Proposal and Agreement), Java and Spring Boot microservices, Jenkins pipelines, and OpenShift deployment"
        - "Present as the opening bullet on all three prior resume versions"
      keywords_hit: [Java, Spring Boot, microservices, Jenkins, "CI/CD", OpenShift]
      defense: "A plain description of the domain and stack worked in for two years. Carries no metric and asserts no individual ownership of the domain."
      interview_risk: "Low. Be ready to name the four microservices and describe what each does."
```

- [ ] **Step 4: Re-rate three priorities**

Set `priority: 1` on `am_b03_audit_trail`, `am_b04_data_retention`, and `am_b05_test_automation` (all currently 2). Without this the intended render order is rejected at load time: `bullet_order` forbids a bullet preceding a strictly-lower-priority bullet **from the same entry**, and `am_b01`/`am_b02` are already priority 1.

- [ ] **Step 5: Downgrade `am_b05.claim_type`**

Change `claim_type: verified` to `claim_type: estimated`. Two of the four numbers it now prints (~50%, ~40%) are estimated, so the bullet is no longer fully verified.

- [ ] **Step 6: Replace the five `medium` phrasings**

```yaml
# am_b04_data_retention
      medium: "**Reduced production data footprint by 40%** and improved active query performance by 25% by building a policy-driven data-retention capability across three microservices; implemented REST lifecycle APIs, integrated **Kafka for event-driven archival**, and enforced archive-before-delete ordering so documents were removed only after a confirmed archive completion event."

# am_b05_test_automation
      medium: "**Reduced manual E2E testing effort by 50% and cross-service defects by 40%** by automating API testing with Postman and Newman in Jenkins with JSON-schema response validation; **raised unit-test coverage to 90%** across four microservices using JUnit 5, Mockito, and WireMock while clearing ~500 SonarQube code smells behind enforced quality gates."

# am_b03_audit_trail
      medium: "Architected an immutable audit-trail system that **cut issue-resolution time by 60%** - delegate-level Kafka triggers with correlation-ID propagation feeding a new consumer that persisted append-only, actor-attributed records in **Elasticsearch** - replacing multi-service log correlation with one filtered query."

# am_b01_dlq_consolidation
      medium: "Redesigned the Kafka dead-letter-queue architecture, consolidating 862 per-consumer DLQ topics across 11 deployments into one shared DLQ per subdomain behind a feature-flagged HELM binding function - **cutting idle topic sprawl by 70% and reclaiming ~80% of wasted partitions**."

# am_b02_row_level_entitlement
      medium: "Co-built a Java **row-level entitlement library** chaining JSON Web Token (JWT) claim validators for multi-tenant operators, pushing claim predicates into **Couchbase N1QL and Elasticsearch** queries behind new secondary indexes so only authorized rows were returned, failing closed with HTTP 403."
```

- [ ] **Step 7: Record the deviations in `docs/DECISIONS.md`**

Add one entry dated 2026-08-03 covering all three: the metric reinstatement, the `am_b05` claim_type downgrade, and the `am_b03`/`am_b04`/`am_b05` priority re-rating — each with the reason given above.

- [ ] **Step 8: Verify the profile still loads**

Run: `.venv/bin/python -m scripts.validate_profile`
Expected: bullet count rises from 47 to 48; still LINT FAILED pending Task 9.

- [ ] **Step 9: Commit**

```bash
git add config/master_profile.yaml docs/DECISIONS.md
git commit -m "content(m8): add Amdocs scene-setter and reinstate estimated metrics"
```

---

### Task 9: Rebuild both bullet_orders and clear the remaining lint

**Files:**
- Modify: `config/master_profile.yaml` (`base_variants`, project bullet phrasings, remaining over-limit shorts)

**Interfaces:**
- Consumes: bullet ids from Tasks 7 and 8.
- Produces: `base_variants.backend` and `base_variants.ml` each holding 13 ids; `lint_profile` returning `[]`.

- [ ] **Step 1: Replace `base_variants.backend`**

```yaml
  backend:
    projects: [clinical_trial_platform, campus_marketplace]
    bullet_order:
      - int_b1
      - int_b2
      - int_b3
      - am_b00_order_management_domain
      - am_b04_data_retention
      - am_b05_test_automation
      - am_b03_audit_trail
      - am_b01_dlq_consolidation
      - am_b02_row_level_entitlement
      - ct_b1
      - ct_b2
      - cm_b1
      - cm_b2
```

`peerchat_peer_discovery` leaves `base_variants.backend.projects`; the entry stays in the profile for JD-specific tailoring.

- [ ] **Step 2: Identify the two Sepsis bullets for the ml variant**

Run:

```bash
.venv/bin/python -c "
import yaml; d=yaml.safe_load(open('config/master_profile.yaml'))
p=[x for x in d['projects'] if x['id']=='sepsis_early_warning'][0]
for b in p['bullets']: print(b['id'], '|', (b.get('phrasings') or {}).get('medium','')[:110])
"
```

Pick the two matching `Himanshu_Resume_Gen.tex`: the **175-feature leakage-safe tabular pipeline** and the **calibrated meta-stacking ensemble**. **Do not assume they are `sepsis_b1`/`sepsis_b2`** — read the phrasings and confirm.

- [ ] **Step 3: Replace `base_variants.ml`**

Same nine experience ids as backend, then the two confirmed Sepsis ids, then `frd_b1` and `frd_b3`. The other four `frd_*` bullets are `ownership_unresolved` and are rejected from any `bullet_order` at load time.

```yaml
  ml:
    projects: [sepsis_early_warning, fake_review_detection]
    bullet_order:
      - int_b1
      - int_b2
      - int_b3
      - am_b00_order_management_domain
      - am_b04_data_retention
      - am_b05_test_automation
      - am_b03_audit_trail
      - am_b01_dlq_consolidation
      - am_b02_row_level_entitlement
      # the two Sepsis ids confirmed in Step 2, in priority order
      - frd_b1
      - frd_b3
```

- [ ] **Step 4: Add emphasis to every project bullet now in a bullet_order**

`ct_b1`, `ct_b2`, `cm_b1`, `cm_b2`, plus the four ml project bullets. Their existing phrasings already match the user's style — **do not rewrite them**, only wrap 1-3 spans per `medium`. Follow the reference resume: bold the metric where there is one (`**557,000+ trials**`, `**AUC from 0.683 to 0.944**`), otherwise the key noun phrase (`**AI Medical Monitor agent**`, `**Java 21, Spring Boot, PostgreSQL**`).

- [ ] **Step 5: Trim the remaining over-limit shorts**

`sepsis_b9` (213), `sepsis_b11` (217), and `frd_b7` (279) exceed the 200-char `short` limit. Trim each to under 200 without changing its claim. These are demoted bullets; the lint ships clean regardless.

- [ ] **Step 6: Check the variant budget and trim if over**

Run:

```bash
.venv/bin/python -c "
import yaml
from src.render.emphasis import parse_emphasis
d=yaml.safe_load(open('config/master_profile.yaml'))
idx={b['id']:b for s in d['projects']+d['experience'] for b in s['bullets']}
for name,v in d['base_variants'].items():
    tot=sum(len(parse_emphasis(idx[i]['phrasings']['medium'])[0]) for i in v['bullet_order'])
    print(name, len(v['bullet_order']), 'bullets,', tot, 'chars')
"
```

Expected: roughly 3,700-3,800 per variant — under the 3,800 lint ceiling but **above the ~3,600 authoring target in the spec**. If a variant exceeds 3,600, trim in this order until it fits: `am_b02` (drop the secondary-indexes clause), then `int_b3` (drop `timeout, or unparseable response`), then `ct_b2`. Never trim a `medium` below 200 chars.

- [ ] **Step 7: Verify the lint is clean**

Run: `.venv/bin/python -m scripts.validate_profile`
Expected: `OK config/master_profile.yaml: ... 48 bullet(s) (4 blocked), base_variants: backend, ml` followed by `LINT OK`.

- [ ] **Step 8: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: green. `tests/render/test_mapping.py` asserts over `bullet_order` **dynamically** (set comparison and relative-index ordering) rather than hardcoding 29, so it should pass unchanged. If `test_unavailable_tier_is_a_hard_error_not_a_silent_downgrade` now skips because every ordered bullet defines a `long` phrasing, that is a legitimate skip, not a failure.

- [ ] **Step 9: Commit**

```bash
git add config/master_profile.yaml
git commit -m "content(m8): cut both base variants to 13 bullets on a one-page budget"
```

---

### Task 10: Bind the real profile to the lint and verify end to end

**Files:**
- Modify: `tests/test_profile_lint.py`

**Interfaces:**
- Consumes: `lint_profile` from Task 6; the content from Tasks 7-9.
- Produces: a regression test binding the real profile to the lint.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_profile_lint.py`:

```python
def test_real_profile_passes_the_lint():
    profile = load_profile("config/master_profile.yaml")
    assert lint_profile(profile) == []


def test_real_variants_stay_within_the_bullet_budget():
    profile = load_profile("config/master_profile.yaml")
    for name, variant in profile.base_variants.items():
        assert len(variant.bullet_order) <= 15, f"{name} has too many bullets"
```

- [ ] **Step 2: Run the tests**

Run: `.venv/bin/pytest tests/test_profile_lint.py -v`
Expected: PASS. If `test_real_profile_passes_the_lint` fails, the reported violations name the exact bullet and rule — **fix the content, not the threshold.**

- [ ] **Step 3: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: green, above the 785 baseline.

- [ ] **Step 4: Re-render the bake-off**

Run: `.venv/bin/python -m scripts.render_bakeoff --variant backend --template profile/template.tex`

- [ ] **Step 5: Verify the PDF is one page**

Run:

```bash
.venv/bin/python -c "
from src.render.parse import parse_pdf
for f in ('build/bakeoff/latex.pdf','build/bakeoff/rendercv.pdf'):
    try:
        p=parse_pdf(f); print(f,'pages=',p.page_count,'chars=',sum(len(' '.join(b.text.split())) for b in p.boxes))
    except Exception as e: print(f,'ERR',e)
"
```

Expected: `pages= 1` for the LaTeX arm, total chars near 4,450. Before this work it was 2 pages / 8,853 chars. If it is still 2 pages the content is over budget — return to Task 9 Step 6 and trim further. **Do not raise `max_pages`.**

- [ ] **Step 6: Commit**

```bash
git add tests/test_profile_lint.py
git commit -m "test(m8): bind the real profile to the phrasing lint"
```

- [ ] **Step 7: Report to the user**

Show: before/after bullet counts (backend 29 → 13, ml 28 → 13), before/after page count (2 → 1), the variant character totals, and the rendered PDF at `build/bakeoff/latex.pdf`. **Do not choose a renderer** — M10's bake-off Task 10 Step 4 stays paused; visual acceptability is the user's call.

**Do not `git push` at any point.**

---

## Notes for the implementer

- The five reinstated Amdocs percentages are the user's own claims about work they personally did, reinstated by explicit decision on 2026-08-03. Do not re-litigate them or quietly soften the numbers.
- If a rewritten bullet would be stronger with a fact its `evidence` does not contain, keep the weaker claim and say so. Fabrication is the one unrecoverable failure.
- `docs/HANDOFF_PHRASING_REWORK.md` is superseded and contains several factual errors — see §7 of the spec. Use the spec, not the handoff.
