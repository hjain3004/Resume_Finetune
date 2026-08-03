# master_profile Phrasing Rework + Emphasis Pipeline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut `config/master_profile.yaml` from 29 rendered bullets to 13 in the user's own voice, give the renderer the ability to bold spans, and add two mechanical guards so neither defect can recur.

**Architecture:** Bullet phrasings gain inline `**markup**`. A pure delimiter-state parser splits that into plain text plus span offsets; the plain text flows to `RenderBullet.text`, while the offsets flow to the LaTeX and RenderCV emitters. This umbrella plan has two execution segments with a mandatory session boundary: Tasks 1-5A are M10 renderer infrastructure; Tasks 6-10 are M8 content hardening. A new pure `src/profile_lint.py` checks length, style, markup validity, and the resolved per-variant character budget; L7 independently enforces the configured page count.

**Tech Stack:** Python 3.11+, PyYAML, pytest, pdfminer.six. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-03-master-profile-phrasing-rework-design.md`

## Global Constraints

- **Never `git push` during this work.** The locally recorded `origin/main` already contains a nearly complete `config/master_profile.yaml`; only eight lines differ locally. Audit the actual remote file and Git history before any future push. This plan does not rewrite published history.
- **No new dependencies and no dependency-file edits.** This work uses the existing PyYAML,
  pytest, and M10-approved `pdfminer.six`; RenderCV remains bake-off-only pending the separate
  renderer decision.
- **Tests never touch the network** and must never require a TeX installation.
- Use `.venv/bin/python` and `.venv/bin/pytest`. Bare `python3` lacks PyYAML.
- Python 3.11+, type hints everywhere, dataclasses at module boundaries, small pure functions, no `print` inside `src/`.
- **Never invent a claim.** Every rewritten bullet must be supported by evidence stored on that same bullet after the atomic edit. Merged bullets copy the relevant source-bullet evidence, keywords, defense, and interview-risk context. Fabrication is the one unrecoverable failure.
- **Preserve every bullet `id`.** The YAML field is `id` (not `bullet_id` — that name exists only on `RenderBullet`). Rewrite `phrasings`; never renumber.
- Blocked bullets (`claim_type` in `ownership_unresolved` / `needs_input`) may not enter any `bullet_order`.
- **Charset:** `ats.forbidden_chars` bans the Unicode similarity/approximation symbol `∼`, multiplication sign, en dash, em dash, curly quotes, and right arrow. Use ASCII `~` for visibly hedged estimates, ASCII hyphens, and straight quotes.
- **Length is measured on PLAIN text**, after stripping `**` markers — that is what renders.
- Generic lint ceiling: **3,800 resolved plain characters** per variant. Final real-profile acceptance: **backend = 3,399** and **ml = 3,537**, both at or below 3,600, using the exact phrasings in Tasks 7-9.
- Baseline before Task 1: **827 passed, 1 deselected**. Task 1 is complete in `aab962c`;
  the current verified state is **839 passed, 1 deselected**, including all 12 emphasis tests.

## Execution boundary

- **M10 session:** Tasks 1-5A only. Commit and stop after the full-suite gate in Task 5A.
- **M8 session:** Tasks 6-10 only, started in a fresh session after M10 is clean.
- Do not combine M10 and M8 changes in one commit or one implementation session.

---

### Task 1: Emphasis parser

**Status:** COMPLETE in `aab962c` (`fix(m10): parse emphasis with delimiter state`). Keep
the task here because Tasks 2-4 consume its exact contract.

**Files:**
- Create: `src/render/emphasis.py`
- Test: `tests/render/test_emphasis.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `parse_emphasis(raw: str) -> tuple[str, tuple[tuple[int, int], ...]]` returning `(plain_text, spans)` where each span is a `(start, end)` half-open offset pair into `plain_text`. Uses a whitespace-based delimiter grammar to handle adjacent markers and detect nesting. Raises `EmphasisError(ValueError)` on unbalanced, empty, or nested markers.

- [x] **Step 1: Write the failing tests**

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


def test_three_separate_spans_are_valid():
    plain, spans = parse_emphasis("Cut **p99** **latency** **here** now.")
    assert plain == "Cut p99 latency here now."
    assert [plain[start:end] for start, end in spans] == ["p99", "latency", "here"]


def test_adjacent_valid_spans_are_valid():
    plain, spans = parse_emphasis("**alpha****beta**")
    assert plain == "alphabeta"
    assert [plain[start:end] for start, end in spans] == ["alpha", "beta"]


def test_leading_whitespace_inside_span_is_rejected():
    with pytest.raises(EmphasisError, match="unbalanced"):
        parse_emphasis("Cut ** p99** latency.")


def test_trailing_whitespace_inside_span_is_rejected():
    with pytest.raises(EmphasisError, match="unbalanced"):
        parse_emphasis("Cut **p99 ** latency.")
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/render/test_emphasis.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.render.emphasis'`

- [x] **Step 3: Write the delimiter-state implementation**

```python
"""Inline emphasis markup. Pure: no I/O, no rendering.

`**text**` marks a span to emphasize. The parser returns the plain text (what
the PDF will contain, and therefore what L7 asserts against) plus offsets into
that plain text. Offsets rather than substrings so repeated text is unambiguous.
"""

_MARKER = "**"


class EmphasisError(ValueError):
    """Raised when emphasis markup is unbalanced, empty, or nested."""


def parse_emphasis(raw: str) -> tuple[str, tuple[tuple[int, int], ...]]:
    """Split `**marked**` text into (plain_text, span offsets into plain_text)."""
    plain_parts: list[str] = []
    spans: list[tuple[int, int]] = []
    cursor = 0
    plain_len = 0
    open_at: int | None = None
    open_plain_start: int | None = None

    while True:
        position = raw.find(_MARKER, cursor)
        if position == -1:
            break

        can_open = (
            position + len(_MARKER) < len(raw)
            and not raw[position + len(_MARKER)].isspace()
        )
        can_close = position > 0 and not raw[position - 1].isspace()

        if open_at is None:
            if not can_open:
                raise EmphasisError(f"unbalanced emphasis marker in {raw!r}")
            before = raw[cursor:position]
            plain_parts.append(before)
            plain_len += len(before)
            open_at = position
            open_plain_start = plain_len
            cursor = position + len(_MARKER)
            continue

        body = raw[open_at + len(_MARKER):position]
        if not body:
            raise EmphasisError(f"empty emphasis span in {raw!r}")
        if can_close:
            assert open_plain_start is not None
            plain_parts.append(body)
            plain_len += len(body)
            spans.append((open_plain_start, plain_len))
            open_at = None
            open_plain_start = None
            cursor = position + len(_MARKER)
        elif can_open:
            raise EmphasisError(f"nested emphasis span in {raw!r}")
        else:
            raise EmphasisError(f"unbalanced emphasis marker in {raw!r}")

    if open_at is not None:
        raise EmphasisError(f"unbalanced emphasis marker in {raw!r}")

    plain_parts.append(raw[cursor:])
    return "".join(plain_parts), tuple(spans)
```

The state machine is required. Pairing every first/second marker is forbidden because the
genuine nested input then looks like two ordinary spans and the nested check becomes dead
code.

- [x] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/render/test_emphasis.py -v`
Expected: `12 passed`

- [x] **Step 5: Commit**

```bash
git add src/render/emphasis.py tests/render/test_emphasis.py
git commit -m "fix(m10): parse emphasis with delimiter state"
```

---

### Task 2: Carry emphasis through the render IR

**Files:**
- Modify: `src/render/emphasis.py` (remove the now-unused `re` import left by `aab962c`)
- Modify: `src/render/model.py` (the `RenderBullet` dataclass)
- Modify: `src/render/mapping.py:66-72` (the `selected` dict comprehension)
- Test: `tests/render/test_model.py`, `tests/render/test_mapping.py`

**Interfaces:**
- Consumes: `parse_emphasis` from Task 1.
- Produces: `RenderBullet(bullet_id: str, text: str, emphasis: tuple[tuple[int, int], ...] = ())` and `_to_render_bullet(bullet: Bullet, requested: str | None) -> RenderBullet`. `text` is always **plain** and markup-free. Existing L7 content checks need no emphasis-specific change.

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
from dataclasses import replace

from src.profile import Phrasings
from src.render.mapping import _to_render_bullet


def test_mapping_strips_markup_and_carries_exact_spans():
    source = next(
        bullet
        for entry in (*PROFILE.projects, *PROFILE.experience)
        for bullet in entry.bullets
    )
    marked = replace(
        source,
        phrasings=Phrasings(
            short="Built an event store.",
            medium="Built **an event store** on PostgreSQL.",
        ),
    )
    rendered = _to_render_bullet(marked, requested=None)
    assert rendered.text == "Built an event store on PostgreSQL."
    assert rendered.emphasis == ((6, 20),)
    assert rendered.text[6:20] == "an event store"
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

In `src/render/emphasis.py`, remove the unused `import re`. In
`src/render/mapping.py`, type the existing resolver and add the imports:

```python
from src.profile import Bullet, MasterProfile
from src.render.emphasis import parse_emphasis
```

```python
def _resolve_text(bullet: Bullet, requested: str | None) -> str:
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
```

Add `_to_render_bullet` below `_resolve_text`, then replace the `selected`
comprehension:

```python
def _to_render_bullet(bullet: Bullet, requested: str | None) -> RenderBullet:
    raw = _resolve_text(bullet, requested)
    plain, spans = parse_emphasis(raw)
    return RenderBullet(bullet_id=bullet.id, text=plain, emphasis=spans)


# Inside build_render_doc:
    selected = {
        bullet.id: _to_render_bullet(bullet, overrides.get(bullet.id))
        for _, bullet in ordered
    }
```

- [ ] **Step 4: Run the full suite to verify nothing regressed**

Run: `.venv/bin/pytest -q`
Expected: green above the 827-test pre-work baseline. The `= ()` default keeps all existing
`RenderBullet(...)` construction sites valid.

- [ ] **Step 5: Commit**

```bash
git add src/render/emphasis.py src/render/model.py src/render/mapping.py tests/render/test_model.py tests/render/test_mapping.py
git commit -m "feat(m10): carry emphasis spans through the render IR"
```

---

### Task 3: Bold in the LaTeX emitter

**Files:**
- Modify: `src/render/latex.py:32-40` (the `_bullets` helper)
- Test: `tests/render/test_latex.py`

**Interfaces:**
- Consumes: `RenderBullet.emphasis` from Task 2, `escape_latex` from `src/render/latex.py`.
- Produces: `_emphasized(bullet: RenderBullet) -> str` — a fully escaped LaTeX string with `\textbf{}` around emphasized spans.

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

In `src/render/latex.py`, import `RenderBullet` and `RenderEntry` alongside `RenderDoc`, add
`_emphasized` above `_bullets`, and change `_bullets` to call it:

```python
def _emphasized(bullet: RenderBullet) -> str:
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


def _bullets(entry: RenderEntry) -> list[str]:
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
- Produces: `_markdown(bullet: RenderBullet) -> str` — the bullet text with `**` markers reinserted around emphasized spans. RenderCV highlights are markdown, so `**` is native. Also locks the already-present RenderCV CLI repair to an output-directory-relative invocation.

- [ ] **Step 1: Write the failing tests**

Append to `tests/render/test_rendercv.py`:

```python
from src.render.emphasis import parse_emphasis
from pathlib import Path

import src.render.rendercv as rendercv_module
from src.render.rendercv import _markdown, render_rendercv


def test_markdown_round_trips_emphasis():
    raw = "Cut **p99 latency** by 40%."
    plain, spans = parse_emphasis(raw)
    bullet = RenderBullet(bullet_id="b1", text=plain, emphasis=spans)
    assert _markdown(bullet) == raw


def test_markdown_leaves_plain_text_untouched():
    bullet = RenderBullet(bullet_id="b1", text="Cut p99 by 40%.")
    assert _markdown(bullet) == "Cut p99 by 40%."


def test_rendercv_cli_runs_from_output_directory(tmp_path, monkeypatch):
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs

    monkeypatch.setattr(rendercv_module.subprocess, "run", fake_run)
    out_pdf = tmp_path / "bakeoff" / "rendercv.pdf"
    assert render_rendercv(_doc(), out_pdf) == out_pdf
    assert captured["command"] == [
        str(Path(".venv/bin/rendercv").resolve()),
        "render",
        "rendercv.yaml",
        "--pdf-path",
        "rendercv.pdf",
    ]
    assert captured["kwargs"] == {
        "cwd": str(out_pdf.parent),
        "check": True,
        "capture_output": True,
    }
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/render/test_rendercv.py -v`
Expected: FAIL — `ImportError: cannot import name '_markdown'`

- [ ] **Step 3: Write the implementation**

In `src/render/rendercv.py`, import `RenderBullet` and `RenderEntry` alongside `RenderDoc`,
type `_entry_dicts(entries: tuple[RenderEntry, ...]) -> list[dict[str, Any]]`, and add
`_markdown` above it:

```python
def _markdown(bullet: RenderBullet) -> str:
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


def _entry_dicts(entries: tuple[RenderEntry, ...]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
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
            item["highlights"] = [_markdown(bullet) for bullet in entry.bullets]
        out.append(item)
    return out
```

Keep the current working-tree repair in `render_rendercv` and make it part of this tested
commit:

```python
    subprocess.run(
        [
            str(Path(".venv/bin/rendercv").resolve()),
            "render",
            yaml_path.name,
            "--pdf-path",
            out_pdf.name,
        ],
        cwd=str(out_pdf.parent),
        check=True,
        capture_output=True,
    )
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


def _doc_with_max_pages(max_pages: object | None) -> RenderDoc:
    layout = {"columns": 1, "contact_in_body": True}
    if max_pages is not None:
        layout["max_pages"] = max_pages
    return _doc(ats={"forbidden_chars": [], "max_file_size_mb": 2.5,
                     "layout": layout,
                     "headings_whitelist": ["Education", "Experience"]})


def _boxes_on_pages(pages: list[int]) -> list[TextBox]:
    return [TextBox(text=f"line {p}", x0=50, y0=700, x1=550, y1=715, page=p)
            for p in pages]


def test_page_count_is_highest_zero_based_index_plus_one():
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


@pytest.mark.parametrize("invalid", [0, -1, "1", True])
def test_invalid_max_pages_is_reported_without_raising(invalid):
    violations = check_page_count(
        _doc_with_max_pages(invalid),
        _pdf(_boxes_on_pages([0])),
    )
    assert len(violations) == 1
    assert "positive integer" in violations[0]
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
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        return [
            "L7 config: ats.layout.max_pages must be a positive integer, "
            f"got {limit!r}"
        ]
    if parsed.page_count > limit:
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

### Task 5A: Version the bake-off operator and close the M10 session

**Files:**
- Modify: `.gitignore` (keep the existing uncommitted `build/` entry)
- Add: `scripts/render_bakeoff.py` (review and version the existing untracked operator)
- Create: `tests/test_render_bakeoff.py`

**Interfaces:**
- Consumes: `build_render_doc`, both renderers, `parse_pdf`, and `run_l7` from Tasks 2-5.
- Produces: `_try(label: str, fn: Callable[[], Path], doc: RenderDoc) -> None` and
  `main() -> int`. A failed renderer is reported as `UN-RUNNABLE`; a completed renderer
  reports its L7 result. The operator never chooses the winning renderer.

- [ ] **Step 1: Verify the repository-state gate is red**

Run:

```bash
git ls-files --error-unmatch scripts/render_bakeoff.py
```

Expected: FAIL because the operator exists only as an untracked working-tree file.

- [ ] **Step 2: Write focused operator tests**

Create `tests/test_render_bakeoff.py`:

```python
from pathlib import Path

import scripts.render_bakeoff as bakeoff
from src.render.model import RenderDoc


def _doc() -> RenderDoc:
    return RenderDoc(
        identity={"name": "Test User"},
        education=(),
        experience=(),
        projects=(),
        skills={},
        section_order=(),
        ats={},
    )


def test_try_reports_l7_pass(monkeypatch, capsys):
    parsed = object()
    monkeypatch.setattr(bakeoff, "parse_pdf", lambda path: parsed)
    monkeypatch.setattr(bakeoff, "run_l7", lambda doc, value: [])

    bakeoff._try("arm (a)", lambda: Path("build/a.pdf"), _doc())

    assert "arm (a): build/a.pdf  L7 PASS" in capsys.readouterr().out


def test_try_reports_renderer_failure_without_raising(capsys):
    def fail() -> Path:
        raise RuntimeError("renderer missing")

    bakeoff._try("arm (b)", fail, _doc())

    output = capsys.readouterr().out
    assert "arm (b): UN-RUNNABLE" in output
    assert "renderer missing" in output
```

- [ ] **Step 3: Run the focused tests**

Run: `.venv/bin/pytest tests/test_render_bakeoff.py -v`
Expected: `2 passed`. The TDD-style red gate for this adoption task is Step 1's failed
tracked-file assertion; the existing operator behavior already satisfies these tests.

- [ ] **Step 4: Apply the typed operator and ignored-output contract exactly**

Keep `build/` in `.gitignore`. In `scripts/render_bakeoff.py`, add the precise callable type
and type `_try` without changing its fail-soft behavior:

```python
from collections.abc import Callable


def _try(
    label: str,
    fn: Callable[[], Path],
    doc: RenderDoc,
) -> None:
    try:
        pdf = fn()
    except Exception as exc:  # noqa: BLE001 - operator reports unavailable arms
        print(f"{label}: UN-RUNNABLE ({exc})")
        return
    violations = run_l7(doc, parse_pdf(pdf))
    status = "PASS" if not violations else f"FAIL ({len(violations)})"
    print(f"{label}: {pdf}  L7 {status}")
    for violation in violations:
        print(f"    - {violation}")
```

- [ ] **Step 5: Run the M10 verification gate**

Run:

```bash
.venv/bin/pytest tests/render/ tests/test_render_bakeoff.py -q
.venv/bin/pytest -q
git diff --check
```

Expected: all tests green; no whitespace errors. Do not run a live TeX or RenderCV smoke in
the test path.

- [ ] **Step 6: Commit the operator and existing related working-tree changes**

```bash
git add .gitignore scripts/render_bakeoff.py tests/test_render_bakeoff.py
git commit -m "feat(m10): version the render bake-off operator"
```

- [ ] **Step 7: Stop the session**

Report the M10 commits and full-suite result. **Do not start Task 6 in this session.** Task 6
is M8 work and begins only in a fresh implementation session.

---

### Task 6: Profile phrasing lint

**Files:**
- Create: `src/profile_lint.py`
- Create: `tests/fixtures/profile_lint_minimal.yaml`
- Modify: `scripts/validate_profile.py`
- Test: `tests/test_profile_lint.py`

**Interfaces:**
- Consumes: `MasterProfile`, `Bullet`, `Phrasings` from `src/profile.py`; `parse_emphasis` / `EmphasisError` from Task 1.
- Produces: `lint_profile(profile: MasterProfile, banned_terms: tuple[str, ...], *, variant_budget: int = VARIANT_BUDGET) -> list[str]` — pure violation strings, empty meaning clean. `scripts.validate_profile._load_banned_terms(path: Path) -> tuple[str, ...]` owns file I/O. Module constants are `MEDIUM_MAX = 400`, `SHORT_MAX = 200`, `MAX_SPANS = 3`, `VARIANT_BUDGET = 3800`.

**Why a separate module, not `load_profile`:** style opinions must never make the profile schema-invalid for the tailor, and folding them in would break the synthetic fixtures in `tests/test_profile.py`.

**Data shapes you need:** `Phrasings(short: str, medium: str | None = None, long: str | None = None)`. `Bullet(id, claim_type, priority, phrasings, evidence, keywords_hit, defense, interview_risk)`. Bullets live on `profile.projects[*].bullets` and `profile.experience[*].bullets`. `profile.base_variants[name].bullet_order` is a tuple of bullet ids.

**Short-only bullets exist** (`pc_b06`, `sepsis_b9`, `sepsis_b11`, `frd_b7` have `medium: None`). Medium-specific checks skip them, but the variant budget counts the renderer's `short` fallback.

- [ ] **Step 1: Create the test fixture**

Create `tests/fixtures/profile_lint_minimal.yaml` exactly as follows. Both `exp_b1` and the
short-only `exp_b2` are ordered so the fixture exercises the real fallback path:

```yaml
schema_version: "0.3.0"
last_updated: "2026-08-03"
ats:
  charset_policy: ascii_strict
  forbidden_chars: ["\u2014"]
  substitutions: {"\u2014": "-"}
identity:
  name: Test User
  email: test@example.com
education:
  - institution: Example University
    degree: Master of Science
    display_date: "Aug. 2025 - May 2027"
skills:
  languages: [Python]
projects:
  - id: proj_one
    name: Project One
    display_title: Project One
    ownership_boundary: "SAFE TO CLAIM: synthetic fixture."
    tech: {tech_line: "Python"}
    keywords: {exact: [Python], topical: [backend]}
    metric_ledger: {}
    metric_scope: {}
    known_gaps: []
    bullets:
      - id: proj_b1
        claim_type: verified
        priority: 1
        phrasings: {short: "Built a project."}
        evidence: ["synthetic fixture"]
        keywords_hit: [Python]
experience:
  - id: exp_one
    employer: Example Corp
    title: Engineer
    scope_line: "Synthetic backend work."
    display_date: "July 2023 - June 2025"
    ownership_boundary: "SAFE TO CLAIM: synthetic fixture."
    bullets:
      - id: exp_b1
        claim_type: verified
        priority: 1
        phrasings:
          short: "SHORT_SENTINEL"
          medium: "MEDIUM_SENTINEL"
        evidence: ["synthetic fixture"]
      - id: exp_b2
        claim_type: verified
        priority: 1
        phrasings: {short: "Shipped a worker."}
        evidence: ["synthetic fixture"]
base_variants:
  backend:
    projects: [proj_one]
    bullet_order: [exp_b1, exp_b2, proj_b1]
do_not_claim: [Kubernetes]
```

- [ ] **Step 2: Write the failing tests**

```python
import json
from pathlib import Path

import pytest

from src.profile import MasterProfile, load_profile
from src.profile_lint import MEDIUM_MAX, SHORT_MAX, lint_profile

FIXTURE = Path("tests/fixtures/profile_lint_minimal.yaml")
_CLEAN_MEDIUM = "Built **an event store** on PostgreSQL for the ordering domain."
_CLEAN_SHORT = "Built an event store on PostgreSQL."
_BANNED = ("robust",)


def _profile(
    tmp_path: Path,
    medium: str = _CLEAN_MEDIUM,
    short: str = _CLEAN_SHORT,
) -> MasterProfile:
    text = FIXTURE.read_text(encoding="utf-8")
    text = text.replace('"MEDIUM_SENTINEL"', json.dumps(medium))
    text = text.replace('"SHORT_SENTINEL"', json.dumps(short))
    path = tmp_path / "p.yaml"
    path.write_text(text, encoding="utf-8")
    return load_profile(path)


def _lint(profile: MasterProfile, *, variant_budget: int = 3800) -> list[str]:
    return lint_profile(profile, _BANNED, variant_budget=variant_budget)


def test_clean_fixture_passes(tmp_path):
    assert _lint(_profile(tmp_path)) == []


def test_overlong_medium_is_reported(tmp_path):
    violations = _lint(_profile(tmp_path, medium="Built **x** " + "y" * MEDIUM_MAX))
    assert any("medium" in v and "exceeds" in v for v in violations)


def test_overlong_short_is_reported(tmp_path):
    violations = _lint(_profile(tmp_path, short="Built " + "y" * SHORT_MAX))
    assert any("short" in v and "exceeds" in v for v in violations)


def test_gerund_opening_is_reported(tmp_path):
    violations = _lint(_profile(tmp_path, medium="Building **a thing** here."))
    assert any("gerund" in v for v in violations)


def test_banned_word_is_reported(tmp_path):
    violations = _lint(_profile(tmp_path, medium="Built **a robust thing** here."))
    assert any("banned" in v and "robust" in v for v in violations)


def test_banned_word_does_not_match_inside_larger_word(tmp_path):
    profile = _profile(tmp_path, medium="Built **system robustness** here.")
    assert not any("banned" in v for v in _lint(profile))


def test_unbalanced_markup_is_reported(tmp_path):
    violations = _lint(_profile(tmp_path, medium="Built **a thing here."))
    assert any("markup" in v for v in violations)


def test_more_than_three_spans_is_reported(tmp_path):
    medium = "Built **a** and **b** and **c** and **d** here."
    violations = _lint(_profile(tmp_path, medium=medium))
    assert any("spans" in v for v in violations)


def test_ordered_bullet_without_emphasis_is_reported(tmp_path):
    violations = _lint(_profile(tmp_path, medium="Built a thing here."))
    assert any("at least one" in v for v in violations)


def test_short_only_bullet_does_not_crash(tmp_path):
    assert _lint(_profile(tmp_path)) == []


def test_variant_budget_counts_short_fallback(tmp_path):
    violations = _lint(_profile(tmp_path), variant_budget=10)
    assert any("budget" in v and "base_variants" in v for v in violations)
```

The explicit `variant_budget` parameter avoids mutating module globals and makes the
short-only fallback test deterministic.

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
import re

from src.profile import Bullet, MasterProfile
from src.render.emphasis import EmphasisError, parse_emphasis

logger = logging.getLogger(__name__)

MEDIUM_MAX = 400
SHORT_MAX = 200
MAX_SPANS = 3
VARIANT_BUDGET = 3800


def _plain(raw: str) -> str:
    return parse_emphasis(raw)[0]


def _contains_term(plain: str, term: str) -> bool:
    pattern = rf"(?<!\w){re.escape(term)}(?!\w)"
    return re.search(pattern, plain, flags=re.IGNORECASE) is not None


def _check_phrasing(
    bullet_id: str,
    tier: str,
    raw: str,
    limit: int | None,
    banned_terms: tuple[str, ...],
    *,
    require_emphasis: bool = False,
) -> list[str]:
    try:
        plain, spans = parse_emphasis(raw)
    except EmphasisError as exc:
        return [f"lint {bullet_id}.{tier}: invalid markup: {exc}"]

    violations: list[str] = []
    if limit is not None and len(plain) > limit:
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
    violations.extend(
        f"lint {bullet_id}.{tier}: contains banned word or phrase {term!r}"
        for term in banned_terms
        if _contains_term(plain, term)
    )
    if require_emphasis and not spans:
        violations.append(
            f"lint {bullet_id}.{tier}: rendered bullet needs at least one emphasis span"
        )
    return violations


def _all_bullets(profile: MasterProfile) -> tuple[Bullet, ...]:
    return tuple(
        bullet
        for source in (*profile.projects, *profile.experience)
        for bullet in source.bullets
    )


def lint_profile(
    profile: MasterProfile,
    banned_terms: tuple[str, ...],
    *,
    variant_budget: int = VARIANT_BUDGET,
) -> list[str]:
    """Every style violation in the profile. Empty list == clean."""
    bullets = _all_bullets(profile)
    ordered_ids = {
        bullet_id
        for variant in profile.base_variants.values()
        for bullet_id in variant.bullet_order
    }

    violations: list[str] = []
    for bullet in bullets:
        violations.extend(
            _check_phrasing(
                bullet.id,
                "short",
                bullet.phrasings.short,
                SHORT_MAX,
                banned_terms,
            )
        )
        if bullet.phrasings.long is not None:
            violations.extend(
                _check_phrasing(
                    bullet.id,
                    "long",
                    bullet.phrasings.long,
                    None,
                    banned_terms,
                )
            )
        if bullet.phrasings.medium is not None:
            violations.extend(
                _check_phrasing(
                    bullet.id,
                    "medium",
                    bullet.phrasings.medium,
                    MEDIUM_MAX,
                    banned_terms,
                    require_emphasis=bullet.id in ordered_ids,
                )
            )

    index = {bullet.id: bullet for bullet in bullets}
    for name, variant in profile.base_variants.items():
        total = 0
        for bullet_id in variant.bullet_order:
            bullet = index[bullet_id]
            raw = bullet.phrasings.medium or bullet.phrasings.short
            try:
                total += len(_plain(raw))
            except EmphasisError:
                total += len(raw)
        if total > variant_budget:
            violations.append(
                f"lint base_variants.{name}: {total} chars of bullet text exceeds "
                f"the one-page budget of {variant_budget}"
            )

    logger.info("profile lint: %d violation(s)", len(violations))
    return violations
```

- [ ] **Step 5: Wire it into the validator without printing a false success**

In `scripts/validate_profile.py`, add these imports and repository-root-relative loader:

```python
from pathlib import Path

from src.profile_lint import lint_profile

_REPO_ROOT = Path(__file__).resolve().parents[1]
_BANNED_WORDS_PATH = _REPO_ROOT / "config" / "banned_words.txt"


def _load_banned_terms(path: Path = _BANNED_WORDS_PATH) -> tuple[str, ...]:
    return tuple(
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
```

In `main`, run lint immediately after `load_profile` succeeds and before the existing `OK`
summary is printed:

```python
    violations = lint_profile(profile, _load_banned_terms())
    if violations:
        for violation in violations:
            print(violation, file=sys.stderr)
        print(f"LINT FAILED: {len(violations)} violation(s)", file=sys.stderr)
        return 1

    sources = (*profile.projects, *profile.experience)
    bullets = sum(len(source.bullets) for source in sources)
    blocked = sum(
        1 for source in sources for bullet in source.bullets if bullet.is_blocked
    )
    print(
        f"OK {args.path}: schema {profile.schema_version}, "
        f"{len(profile.projects)} project(s), {len(profile.experience)} experience "
        f"entry(ies), {bullets} bullet(s) ({blocked} blocked), "
        f"base_variants: {', '.join(sorted(profile.base_variants)) or '(none)'}"
    )
    print("LINT OK")
    return 0
```

Do not leave the old unconditional `OK ...` print above the lint call. The success summary
must execute only on the clean path.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_profile_lint.py -v`
Expected: 11 passed.

Then run: `.venv/bin/python -m scripts.validate_profile`
Expected: **exits 1 with LINT FAILED and no `OK` line** — violations on `int_b7`
(overlong and banned `robust`), `int_b8` (overlong), overlong shorts on `int_b1`,
`sepsis_b9`, `sepsis_b11`, and `frd_b7`, missing emphasis on ordered medium phrasings,
and over-budget variants. Tasks 7-9 clear these exact failures.

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
- Produces: rewritten `phrasings` on `int_b1`, `int_b2`, `int_b3`; merged supporting fields on `int_b2`/`int_b3`; trimmed `short` on `int_b1`; exact lint-clean `medium` text on `int_b7` and `int_b8`.

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
      medium: "Engineered **exactly-once money movement** with INSERT-first idempotency reservation, atomic ON CONFLICT claims, and SHA-256 payload fingerprints, proven by an **8-way duplicate harness** to make one vendor call; the underlying real-time transfer adapter supported 8 transaction types with three-layer settlement validation."
```

Both halves are supported by existing evidence: `int_b2.evidence` covers the idempotency state machine and the 8-way harness; `int_b4.evidence` covers the 8 request types and the three-layer success condition. **No new claim is introduced.**

- [ ] **Step 4: Replace `int_b3.phrasings.medium`** — merges `int_b3` (fail-closed AML) with `int_b8` (security hardening)

```yaml
      medium: "Designed a **fail-closed AML sanctions gateway** that errors on backend faults or invalid responses instead of returning a false clear, serving REST/JSON and legacy SOAP/XML from shared orchestration; hardened all four services with **credential isolation, recursive PII redaction, and XML-injection resistance**."
```

- [ ] **Step 5: Replace `int_b3.phrasings.short`**

```yaml
      short: "Designed a fail-closed AML sanctions screening gateway serving REST and legacy SOAP consumers, with credential isolation and PII redaction."
```

- [ ] **Step 6: Merge the supporting fields onto the surviving bullets**

Append these two exact evidence strings from `int_b4` to `int_b2.evidence`:

```yaml
          - "8 request types: PESALINK (IDENTIFICATION_VERIFICATION, CREDIT_TRANSFER, PHONE_/WALLET_CREDIT_TRANSFER) + PESALINK_LOOKUP (QUERY/REGISTER/UPDATE/DELINK_CUSTOMER)"
          - "Success requires all three: general_data.error_code 00 AND core_response.olErrorCode 0 AND pesalinkDetails.err_code 000"
```

Replace `int_b2.keywords_hit` and `defense`, then append the shown paragraph to its existing
`interview_risk`:

```yaml
        keywords_hit: ["idempotency", "async", "PostgreSQL", "payments", "distributed systems", "real-time payments", "interbank transfer", "Python", "FastAPI"]
        defense: "Fully code-backed. The idempotency state machine and concurrency harness are supported by int_b2's original evidence; the 8 transfer types and three-layer settlement condition are copied from int_b4's evidence."
```

```text
Also rehearse the eight transfer request types and the three independent success codes. The
adapter declared success only when the ESB, core-banking, and PesaLink network layers all
returned their success values.
```

Append these exact evidence strings from `int_b8` to `int_b3.evidence`:

```yaml
          - "Inbound message_validation block (api_user/api_password/token) parsed then discarded; service injects its own vendor credentials server-side"
          - "pydantic.SecretStr for all credentials; recursive redaction of api_user/api_password/token/password and x-api-key/authorization headers"
          - "redact_pii() preserves last 4 chars only, applied across JSON and XML name/passport/dob/nationality fields"
```

Replace `int_b3.keywords_hit` and `defense`, then append the shown paragraph to its existing
`interview_risk`:

```yaml
        keywords_hit: ["AML", "sanctions screening", "OFAC", "SOAP", "XML", "fail-closed design", "regulatory compliance", "secrets management", "PII redaction", "XML injection", "security", "authentication"]
        defense: "Ownership of the AML gateway is explicitly documented. The merged credential-isolation, PII-redaction, and XML-hardening claims are code-backed across the four adapter services; the bullet makes no deployment claim."
```

```text
For the merged security clause, be ready to explain why caller-supplied vendor credentials
are parsed and discarded, which fields recursive redaction covers, and how lxml plus escaped
outbound interpolation address XML bombs and XML injection.
```

- [ ] **Step 7: Replace the two demoted over-limit mediums exactly**

```yaml
# int_b7.phrasings.medium
          medium: "Added a RabbitMQ async path with durable delivery and a dedicated consumer (prefetch 10) returning 202 Accepted to decouple slow identity lookups from request threads; implemented HMAC-SHA256-signed webhooks over canonical JSON with a 5-attempt backoff ladder running as post-response tasks on isolated database sessions."

# int_b8.phrasings.medium
          medium: "Hardened all four services with a credential-isolation boundary that discarded caller-supplied vendor credentials, SecretStr handling, recursive credential and PII redaction before persistence, XML-injection and XML-bomb resistance, and correlation-ID logging that could not break the request path."
```

These replacements remove the banned word `robust` from `int_b7` and keep both demoted
bullets available to the tailor.

- [ ] **Step 8: Verify the profile still loads**

Run: `.venv/bin/python -m scripts.validate_profile`
Expected: still LINT FAILED. No `int_*` length or banned-term violations remain. Missing-
emphasis violations remain temporarily on `int_b4`-`int_b8` because the old base variants
still order them; Task 9 removes those demoted IDs from both `bullet_order` lists.

- [ ] **Step 9: Commit**

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
- Produces: new bullet `am_b00_order_management_domain`; rewritten `phrasings` and non-contradictory defenses on `am_b01`-`am_b05`; `priority: 1` on `am_b03`/`am_b04`/`am_b05`; `claim_type: estimated` on all three bullets printing estimated metrics; five `metric_ledger` entries flipped to `renderable: true`; an explicit Amdocs-scoped exception replacing the stale two-estimate cap.

- [ ] **Step 1: Flip the five metric_ledger entries to renderable**

In `amdocs_software_developer.metric_ledger`, replace the five entries exactly. Leave
`provenance: estimated` unchanged — legal because `ESTIMATED` is not in
`NON_RENDERABLE_PROVENANCES`:

```yaml
      purge_footprint:      { value: "~40%", provenance: estimated, renderable: true, note: "Reinstated 2026-08-03 by user decision; present on the interview-tested resume." }
      purge_query_gain:     { value: "~25%", provenance: estimated, renderable: true, note: "Reinstated 2026-08-03 by user decision; present on the interview-tested resume." }
      qa_effort_reduction:  { value: "~50%", provenance: estimated, renderable: true, note: "Reinstated 2026-08-03 by user decision; present on the interview-tested resume." }
      defect_reduction:     { value: "~40%", provenance: estimated, renderable: true, note: "Reinstated 2026-08-03 by user decision; present on the interview-tested resume." }
      resolution_time_gain: { value: "~60%", provenance: estimated, renderable: true, note: "Reinstated 2026-08-03 by user decision; present on the interview-tested resume." }
```

Replace the stale policy comment immediately above `metric_ledger`:

```yaml
    # ESTIMATED-METRIC POLICY -- USER-APPROVED AMDOCS EXCEPTION, 2026-08-03:
    # purge_footprint, purge_query_gain, qa_effort_reduction, defect_reduction,
    # and resolution_time_gain may appear together in the backend and ml base
    # variants. Keep every value visibly hedged with ASCII "~", preserve
    # provenance: estimated, and keep each bullet's interview defense. This
    # exception authorizes no other estimated metric.
```

- [ ] **Step 2: Rewrite the `am_gap_estimated_metrics` known_gap**

Its current `fix` reads "Keep it that way" — now factually stale. Replace `detail` and `fix`:

```yaml
      detail: "Five figures (~40%, ~25%, ~50%, ~40%, ~60%) are two-year-old reconstructions with no reproducible measurement behind them. The user reinstated all five on 2026-08-03: they appear on the interview-tested resume and describe work the user personally did."
      fix: "USER-APPROVED EXCEPTION (2026-08-03): print all five together in the backend and ml base variants, visibly hedged with ASCII '~'. Rehearse each defense verbatim and describe them as reconstructed estimates, not instrumented measurements."
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

Change `am_b05.claim_type: verified` to `estimated`. Confirm `am_b03` and `am_b04` remain
`estimated`. These are the three bullets that print the five reconstructed figures.

- [ ] **Step 6: Replace the five `medium` phrasings**

```yaml
# am_b04_data_retention
      medium: "**Reduced production data footprint by ~40% and query time by ~25%** with policy-driven retention across three microservices; built REST lifecycle APIs, **Kafka-based archival**, and archive-before-delete ordering so removal followed confirmed archive completion."

# am_b05_test_automation
      medium: "**Reduced manual E2E effort by ~50% and cross-service defects by ~40%** with Postman/Newman tests in Jenkins and JSON-schema validation; **raised unit coverage to 90%** across four services using JUnit 5, Mockito, and WireMock while clearing ~500 SonarQube smells."

# am_b03_audit_trail
      medium: "Architected an immutable audit-trail system that **cut issue-resolution time by ~60%** - delegate-level Kafka triggers with correlation-ID propagation feeding a new consumer that persisted append-only, actor-attributed records in **Elasticsearch** - replacing multi-service log correlation with one filtered query."

# am_b01_dlq_consolidation
      medium: "Redesigned the Kafka dead-letter-queue architecture, consolidating 862 per-consumer DLQ topics across 11 deployments into one shared DLQ per subdomain behind a feature-flagged HELM binding function - **cutting idle topic sprawl by 70% and reclaiming ~80% of wasted partitions**."

# am_b02_row_level_entitlement
      medium: "Co-built a Java **row-level entitlement library** chaining JSON Web Token (JWT) claim validators for multi-tenant operators, pushing claim predicates into **Couchbase N1QL and Elasticsearch** queries behind new secondary indexes so only authorized rows were returned, failing closed with HTTP 403."
```

- [ ] **Step 7: Replace the three stale defense strings**

```yaml
# am_b03_audit_trail.defense
        defense: "The ~60% resolution-time figure is a reconstructed estimate from before/after support work, not an instrumented metric. The user approved printing it on 2026-08-03. Defend it as hours of multi-service log correlation reduced to one filtered query, and state the estimation method plainly."

# am_b04_data_retention.defense
        defense: "The ~40% footprint and ~25% query-time figures are reconstructed estimates from rollout data-distribution analysis, not reproducible measurements. The user approved printing both on 2026-08-03. The archive-before-delete mechanism is code-path detail and remains the strongest defense."

# am_b05_test_automation.defense
        defense: "The 90% coverage and ~500 SonarQube-smell figures are doc-backed. The ~50% E2E-effort and ~40% defect reductions are reconstructed estimates approved for printing on 2026-08-03. Distinguish the two provenance classes explicitly if challenged."
```

- [ ] **Step 8: Record the scoped exception in `docs/DECISIONS.md`**

Append this exact entry:

```markdown
## 2026-08-03: Amdocs estimated-metric exception for the two base variants

**Decision:** By explicit user direction, the five named reconstructed Amdocs metrics
(`~40%` data footprint, `~25%` query time, `~50%` E2E effort, `~40%` cross-service defects,
and `~60%` issue-resolution time) may appear together in both the backend and ML base
resumes. This is a scoped exception to the profile's former two-estimate cap, not a general
relaxation. All five remain `provenance: estimated`, stay visibly hedged with ASCII `~`, and
retain interview-defense text. `am_b05` changes from `claim_type: verified` to `estimated`;
`am_b03` and `am_b04` remain estimated. All three move to priority 1 because the reinstated
impact makes them flagship Amdocs bullets and their intended order must satisfy the
same-entry priority invariant.
```

- [ ] **Step 9: Verify the profile still loads**

Run: `.venv/bin/python -m scripts.validate_profile`
Expected: bullet count rises from 47 to 48; still LINT FAILED pending Task 9.

- [ ] **Step 10: Commit**

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

- [ ] **Step 2: Verify the already-resolved Sepsis IDs against the loaded profile**

The design review resolved the IDs: `sepsis_b3` is the calibrated meta-stacking ensemble
(priority 1), and `sepsis_b8` is the leakage-safe 175-feature pipeline (priority 3). Verify
that the current profile still says so:

```bash
.venv/bin/python -c "
from src.profile import load_profile
p=load_profile('config/master_profile.yaml')
s=next(x for x in p.projects if x.id=='sepsis_early_warning')
for b in s.bullets:
    if b.id in {'sepsis_b3','sepsis_b8'}:
        print(b.id, b.priority, b.phrasings.medium)
"
```

Expected: `sepsis_b3 1` describes calibrated meta-stacking; `sepsis_b8 3` describes the
175-feature leakage-safe pipeline. If those facts differ, stop because the authoritative
profile changed after this plan was written.

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
      - sepsis_b3
      - sepsis_b8
      - frd_b1
      - frd_b3
```

- [ ] **Step 4: Replace the eight selected project mediums exactly**

```yaml
# ct_b1
          medium: "Built a **12-service Python and FastAPI microservices platform** for synthetic clinical trial data - generation, analytics, quality scoring, electronic data capture, and security - deployed via **Docker Compose, Kubernetes, and Terraform**."

# ct_b2
          medium: "Led the platform's **security service** - authentication and access control across the microservice boundary for regulated clinical trial data."

# cm_b1
          medium: "Built the backend for a campus peer-to-peer marketplace as primary developer on a 3-person team - a **17,000-line Java 21 and Spring Boot service** with 20 REST controllers, 24 JPA entities, and **30 Flyway-controlled PostgreSQL migrations**."

# cm_b2
          medium: "Owned the listing and user domains, implementing **listing search and Amazon S3-backed photo upload**, plus role-based access control over **Spring Security with JWT authentication** and an OAuth2 resource server."

# sepsis_b3
          medium: "Designed a **calibrated meta-stacking ensemble** isotonically calibrating XGBoost and GRU-D outputs and fusing them through a logistic-regression stacker, **lifting normalized utility about 10%** over the best single model."

# sepsis_b8
          medium: "Built a **leakage-safe 175-feature pipeline** over 40 raw clinical signals - per-patient temporal imputation, deltas, rolling statistics, and measurement-frequency features that treat missing labs as signal - under a **strict patient-level split**."

# frd_b1
          medium: "Owned the data-engineering layer of a six-stage fake-review detection pipeline: a **PySpark ETL over 608K Yelp reviews** deriving 260K reviewer and 5K seller behavioral profiles, persisted as **partitioned Delta Lake tables** with OLAP cubes and eight automated quality checks."

# frd_b3
          medium: "Ran a seven-configuration layer ablation showing **behavioral signals plateaued at 0.815 AUC / 0.438 F1** while adding the transformer text layer lifted them to **0.936 AUC / 0.741 F1**, isolating the text layer's true contribution."
```

These strings contain only claims already supported on the same bullet. In particular, the
withdrawn fake-review figures `0.683` and `0.944` do not return.

- [ ] **Step 5: Trim the remaining over-limit shorts**

Replace the three shorts exactly:

```yaml
# sepsis_b9
          short: "Evaluated five tabular models, GRU-D, and two clinical-rule baselines on one patient-level split, tuning thresholds against asymmetric clinical utility rather than accuracy."

# sepsis_b11
          short: "Made results reproducible with pinned dependencies, seeded splits, saved model/calibrator artifacts, and a three-notebook run order reconstructing every metric on one GPU."

# frd_b7
          short: "Measured cross-layer redundancy with Jaccard overlap at multiple top-K cutoffs, showing rule and clustering layers re-flagged many of the same reviewers while text added independent signal."
```

- [ ] **Step 6: Assert the exact variant totals**

Run:

```bash
.venv/bin/python -c "
import yaml
from src.render.emphasis import parse_emphasis
d=yaml.safe_load(open('config/master_profile.yaml'))
idx={b['id']:b for s in d['projects']+d['experience'] for b in s['bullets']}
for name,v in d['base_variants'].items():
    def resolved(i):
        p=idx[i]['phrasings']; return p.get('medium') or p['short']
    tot=sum(len(parse_emphasis(resolved(i))[0]) for i in v['bullet_order'])
    print(name, len(v['bullet_order']), 'bullets,', tot, 'chars')
"
```

Expected exactly:

```text
backend 13 bullets, 3399 chars
ml 13 bullets, 3537 chars
```

Any other total means an exact Task 7-9 phrasing was copied incorrectly. Fix the mismatch;
do not improvise additional trimming and do not raise either threshold.

- [ ] **Step 7: Verify the lint is clean**

Run: `.venv/bin/python -m scripts.validate_profile`
Expected: `OK config/master_profile.yaml: ... 48 bullet(s) (4 blocked), base_variants: backend, ml` followed by `LINT OK`.

- [ ] **Step 8: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: green. The bullet-order assertions are dynamic. Task 2 moved the unavailable-tier
coverage onto a synthetic bullet, so this content edit must not introduce a new skip.

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
- Produces: regression tests binding the real profile to lint, exactly 13 bullets per variant,
  and the measured plain-text totals (`backend=3399`, `ml=3537`).

- [ ] **Step 1: Add the real-profile regression tests**

Append to `tests/test_profile_lint.py` and add the shown imports:

```python
from scripts.validate_profile import _load_banned_terms
from src.render.emphasis import parse_emphasis

_EXPECTED_REAL_TOTALS = {"backend": 3399, "ml": 3537}


def _real_variant_total(profile: MasterProfile, name: str) -> int:
    index = {
        bullet.id: bullet
        for source in (*profile.projects, *profile.experience)
        for bullet in source.bullets
    }
    return sum(
        len(
            parse_emphasis(
                index[bullet_id].phrasings.medium
                or index[bullet_id].phrasings.short
            )[0]
        )
        for bullet_id in profile.base_variants[name].bullet_order
    )


def test_real_profile_passes_the_lint():
    profile = load_profile("config/master_profile.yaml")
    assert lint_profile(profile, _load_banned_terms()) == []


def test_real_variants_have_exact_shape_and_budget():
    profile = load_profile("config/master_profile.yaml")
    assert set(profile.base_variants) == set(_EXPECTED_REAL_TOTALS)
    for name, expected_total in _EXPECTED_REAL_TOTALS.items():
        assert len(profile.base_variants[name].bullet_order) == 13
        assert _real_variant_total(profile, name) == expected_total
        assert expected_total <= 3600
```

- [ ] **Step 2: Run the tests**

Run: `.venv/bin/pytest tests/test_profile_lint.py -v`
Expected: PASS. If `test_real_profile_passes_the_lint` fails, the reported violations name the exact bullet and rule — **fix the content, not the threshold.**

- [ ] **Step 3: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: green above the 827-test pre-work baseline.

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

Expected: `pages= 1` for the LaTeX arm, with total extracted characters near the reference
PDF range. Before this work it was 2 pages / 8,853 characters. Report the RenderCV page count
and L7 result separately; it does not decide the paused renderer bake-off.

If the LaTeX arm is still two pages, **stop and show the user the PDF and measurements**.
Do not improvise new wording, change the exact Task 7-9 totals, or raise `max_pages`; that is
a measured deviation requiring a user decision and a `docs/DECISIONS.md` entry.

- [ ] **Step 6: Commit**

```bash
git add tests/test_profile_lint.py
git commit -m "test(m8): bind the real profile to the phrasing lint"
```

- [ ] **Step 7: Report to the user**

Show: before/after bullet counts (backend 29 → 13, ml 28 → 13), before/after page count
(2 → 1), exact totals (3,399 / 3,537), and `build/bakeoff/latex.pdf`. **Do not choose a
renderer** — the renderer-selection step in the original M10 bake-off plan remains paused;
visual acceptability is the user's call.

**Do not `git push` at any point.**

---

## Notes for the implementer

- The five reinstated Amdocs percentages are the user's own claims about work they personally did, reinstated by explicit decision on 2026-08-03. Do not remove them or change their values; retain the explicit ASCII `~` hedge because their provenance remains estimated.
- If a rewritten bullet would be stronger with a fact its `evidence` does not contain, keep the weaker claim and say so. Fabrication is the one unrecoverable failure.
- `docs/HANDOFF_PHRASING_REWORK.md` is superseded and contains several factual errors — see §7 of the spec. Use the spec, not the handoff.
