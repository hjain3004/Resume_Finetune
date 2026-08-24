# M8P-5 — Deterministic Tailored Render, Rendered Line Check, and L7 Execution Design

**Date:** 2026-08-24

**Status:** Approved for planning. Tasks 1–4 may be implemented in parallel with
M8P-3R; tasks 5–6 require M8P-3R merged.

**Phase:** 3 (M8 Tailoring)

**Predecessors:** M10 (renderer bake-off, LaTeX selected, L7 built), M8P-3
(`9a1fd9c`), and — for the bundle-loading half only — M8P-3R.

**Umbrella:** `docs/superpowers/specs/2026-08-24-phase3-parallel-workstreams-design.md`

## 1. Goal

Turn an accepted `TailoredDraft` into the already-selected LaTeX arm's PDF, prove the
PDF still says what the draft meant, close the `render_line_check = "pending"` debt
left by M8P-3, and publish the result atomically under a deterministic per-application
layout.

M8P-5 makes **no model call of any kind**. It is entirely deterministic code plus one
`pdflatex` subprocess.

## 2. The renderer is not being redesigned

M10 already built both arms and selected LaTeX. `profile/template.tex` already uses
`left=0.20in, right=0.20in, top=0.20in, bottom=0.20in` — the user's "margins as small
as safely practical" preference is *already implemented*, and nothing in the current
documentation shows it to be inadequate. M8P-5 therefore:

- does not change the template's geometry, fonts, spacing macros, or section macros;
- does not change `src/render/latex.py`'s emission logic;
- does not revisit the M10 arm decision.

What it adds is the missing **input path** (a tailored draft, rather than a base
variant) and the missing **verification** (rendered line counts, vertical page bleed,
metric survival, emphasis actually rendering bold, invisible text).

The one geometry-adjacent addition is a *configurable, default-off* printable-margin
advisory (§6.7). It is advisory precisely because 0.20in is the user's accepted
choice, and a gate that failed the user's own template would be a bug, not a finding.

## 3. Fixed boundaries

- No model call, no network, no tool use, no shell beyond the single `pdflatex`
  invocation the existing `render_latex()` already performs.
- No SQLite write of any kind.
- No new dependency. `pdfminer.six` is already a runtime dependency; `pdflatex` is an
  external binary already required by the selected arm.
- Tests never call `pdflatex`. Every geometry test runs against PDF fixtures committed
  under `tests/fixtures/render/`, recorded once with the existing
  `scripts/record_render_fixture.py`.
- `src/tailor/s3.py`, `src/tailor/g1.py`, `src/tailor/s3_pipeline.py`,
  `scripts/tailor_s3.py`, and every existing M8P-3 test are read-only.
- `src/render/mapping.py`, `src/render/model.py`, `src/render/parse.py`, and
  `src/render/latex.py` are read-only imports. M8P-5 adds new modules rather than
  editing them, so it cannot collide with any other branch.
- Rendered artifacts contain the user's real name, phone, and email. They are written
  only under a **gitignored** path (see §8 and umbrella decision D4).

## 4. Why the draft alone cannot be rendered

`TailoredDraft` is privacy-minimised by construction (M8P-3 design §4): it carries
bullet ids, owners, text, plain text, emphasis spans, skills, project/experience ids,
and the alignment fingerprint. It carries **no** identity, education, project display
titles, tech lines, date ranges, or ATS policy block.

The renderer therefore re-hydrates those from the local `config/master_profile.yaml`
and binds the two together by recomputing the alignment fingerprint. If the local
profile has changed since the draft was produced, the fingerprints disagree and the
render fails closed. This is the mechanism that makes "the PDF matches the approved
draft" a checkable statement rather than a hope.

## 5. `TailoredDraft` + `MasterProfile` → `RenderDoc`

`src/render/tailored.py` exposes:

```python
def render_doc_from_draft(profile: MasterProfile, draft: TailoredDraft) -> RenderDoc
```

Rules, all deterministic and all failing closed:

1. Every `draft.project_ids` entry must resolve to a profile project; every
   `draft.experience_ids` entry to a profile experience. Unknown id ⇒ error.
2. Section order is the fixed canonical skeleton
   `("Education", "Experience", "Projects", "Technical Skills")`, identical to
   `src/render/mapping.py`'s `_SECTION_ORDER`. It is not derived from the draft.
3. Every section name must appear in `profile.ats.headings_whitelist`.
4. Bullets are placed under their **canonical owner** (`DraftBullet.owner_id` /
   `owner_kind`), never inferred from naming. Within an owner, bullets keep the
   draft's global order.
5. Every bullet in `draft.bullets` must be emitted exactly once. A bullet whose owner
   is not among the selected projects/experiences is an error, not a silent drop.
6. Bullet text is the draft's own marked `text`, re-parsed through
   `parse_emphasis()`. The re-parsed plain text and spans must equal the draft's
   stored `plain_text` and `emphasis`; a mismatch is an error. (This duplicates a
   check M8P-3R adds inside G1, deliberately: the renderer must not depend on an
   upstream gate having run.)
7. Skills are emitted in the draft's category order, with the draft's term order.
8. `identity`, `education`, and `ats` come from the profile verbatim.
9. `alignment_fingerprint` is recomputed from the profile plus the draft's structural
   projection and must equal `draft.alignment_fingerprint`.

The function is pure: no filesystem, no subprocess.

## 6. Rendered-geometry layer and L7 extension

### 6.1 Why a new geometry module

`src/render/parse.py` returns `LTTextContainer`-level boxes. Line counts and font
weight need `LTTextLine` and `LTChar`. Rather than change the shared parser — which
would conflict with any other branch touching render — M8P-5 adds
`src/render/lines.py`, which performs its own `extract_pages()` walk and returns:

```python
@dataclass(frozen=True)
class RenderedLine:
    text: str
    x0: float; y0: float; x1: float; y1: float
    page: int
    max_font_size: float
    bold_run_texts: tuple[str, ...]   # contiguous runs whose LTChar fontname contains "Bold"
    min_font_size: float

@dataclass(frozen=True)
class RenderedPage:
    number: int
    width: float
    height: float
    lines: tuple[RenderedLine, ...]

def parse_rendered_lines(path: str | Path) -> tuple[RenderedPage, ...]: ...
def locate_text_lines(pages, needle_plain: str) -> tuple[RenderedLine, ...]: ...
```

`locate_text_lines` finds the shortest contiguous run of lines, in document order,
whose whitespace-normalised concatenation contains the whitespace-normalised needle.
That run is the bullet's rendered extent, and `len(run)` is its rendered line count.
If no run matches, the caller reports a survival failure, not a line count.

### 6.2 `check_bullet_line_counts` — closing the `render_line_check` debt

`TAILORING_METHODOLOGY.md` §4 L4 requires "every modified bullet ≤ 2 lines rendered".
M8P-3 honestly refused to fake this with a character threshold. M8P-5 measures it:

```python
def check_bullet_line_counts(doc: RenderDoc, pages, modified_bullet_ids: frozenset[str],
                             max_lines: int = 2) -> list[str]
```

Only **modified** bullets are subject to the limit, exactly as the methodology states.
Unmodified canonical bullets are the user's own authored text and are out of scope.

### 6.3 `check_metrics_survive`

Every numeric token in every draft bullet's plain text (using the same regex the S3
contract uses for its numeric-multiset rule) must appear in the extracted PDF text
with the same multiset per bullet. This catches a LaTeX escape or ligature that
silently mangles "40%" or "~3x" even when the surrounding words survive.

### 6.4 `check_emphasis_rendered`

For every bullet with non-empty `emphasis`, each emphasised substring must appear
inside a bold run on the page. This proves `\textbf{}` actually reached the PDF rather
than being escaped away.

### 6.5 `check_within_page_vertical`

The existing `check_within_page` only tests horizontal bleed. Add the vertical
counterpart: `y0 < -tolerance` or `y1 > page_height + tolerance` is text off the top
or bottom of the paper. With 0.20in margins this is the realistic failure mode when a
tailored bullet grows the document.

### 6.6 `check_no_invisible_text`

Flag any rendered line whose `min_font_size <= 0.5` (effectively zero-size text) — the
"hidden keyword" pattern `TAILORING_SPEC.md` §2.6 and `TAILORING_METHODOLOGY.md` §1
both explicitly forbid. This is a defensive check: the deterministic renderer cannot
produce it today, and the check exists so that it stays impossible.

### 6.7 `check_printable_margin` — advisory, default off

Reads `ats.layout.min_margin_in`. If the key is absent (the current state), the check
returns no violations. If present, it flags any text whose bounding box sits closer to
a page edge than that value. This exists so the user can opt into a printer-safe floor
later without anyone silently widening the template's accepted 0.20in geometry now.

### 6.8 `run_l7_tailored`

A new aggregate that runs every existing `run_l7` check plus §6.2–§6.7, taking the
modified-bullet id set as an argument. `run_l7` itself is unchanged so the M10 tests
and `scripts/render_bakeoff.py` keep working.

Header/footer collision is already covered: the template sets `\fancyhf{}` and
`\renewcommand{\headrulewidth}{0pt}`, so there is no header content to collide with;
`check_contact_in_body` plus `check_no_overlap` plus §6.5 cover the remaining band
risks.

## 7. Render outcomes — fail closed

`RenderOutcomeKind`:

- `fingerprint_mismatch` — the draft was not derived from the local profile;
- `mapping_failure` — §5 rule violated;
- `renderer_unavailable` — `pdflatex` not on PATH;
- `renderer_failure` — nonzero exit, timeout, or no PDF produced;
- `parse_failure` — the produced PDF could not be parsed;
- `l7_failure` — one or more L7 violations;
- `already_published` — an accepted `render_result.json` already exists for this
  application and its input fingerprint matches; the run is a no-op success and does
  not re-render;
- `conflict` — an accepted `render_result.json` exists with a *different* input
  fingerprint; refuse rather than overwrite;
- `valid`.

Only `valid` publishes. `l7_failure` carries the complete violation list so
diagnostics are never collapsed to one string.

## 8. Deterministic layout, naming, and atomic publication

```
applications/{company-slug}-{role-slug}/
├── resume.tex                 # the exact source compiled
├── Himanshu_Jain_Resume.pdf   # name from ats.filename_pattern
├── render_result.json         # schema_version "m8p5.render_result.v1"  (commit marker)
└── l7_report.json             # full violation list, empty on pass
```

- `company-slug` and `role-slug` are produced by one shared `slugify()`: casefold,
  non-alphanumeric runs → `_`, strip leading/trailing `_`. Deterministic and stable.
- The PDF filename comes from `profile.ats.filename_pattern`, so what an ATS receives
  is unchanged from the base-variant behaviour.
- Publication order is: render and verify inside a temporary directory, then write
  `resume.tex`, the PDF, and `l7_report.json` into the application directory, and
  write `render_result.json` **last** via `write_json_atomic()`. `render_result.json`
  is the commit marker: its presence means every other file is complete.
- An existing `render_result.json` is never overwritten. Same input fingerprint ⇒
  `already_published`; different ⇒ `conflict`.
- `render_result.json` records: schema version, job id, company, title,
  `alignment_fingerprint`, `s3_bundle_schema_version`, the source and PDF paths, the
  PDF SHA-256, page count, file size, the modified-bullet ids, per-modified-bullet
  rendered line counts, the L7 pass/fail verdict, and `render_line_check` set to
  `"pass"` or `"fail"` — the real verdict M8P-3 deliberately left `"pending"`.

**`applications/` is added to `.gitignore`.** Rendered PDFs embed the user's name,
phone, and email, and `origin` is public. This deviates from
`TAILORING_METHODOLOGY.md` §3's "resumes live as source in git" and requires the
user's decision (umbrella D4) before the publication task lands.

The date-organised `applications/by-date/` view and `applications/INDEX.md` described
in the methodology are **deferred to M8P-7**, where more than one application exists
to index.

## 9. What can be built before M8P-3R merges

| Component | Parallel-safe? | Verified with |
|---|---|---|
| `render_doc_from_draft` | Yes | Synthetic in-test `TailoredDraft` objects plus the real `config/master_profile.yaml` |
| `src/render/lines.py` | Yes | The two committed PDF fixtures plus two newly recorded ones |
| L7 extension checks §6.2–§6.7 | Yes | Recorded PDF fixtures |
| `slugify`, layout paths, `render_result` schema | Yes | Pure unit tests |
| Bundle loading, CLI, publication of a real bundle | **No** — needs M8P-3R's `parse_s3_bundle` | — |

## 10. Explicit non-goals

M8P-5 does not implement or start: G2, G3, the review packet, feedback capture, taste
capture, gap aggregation, the `by-date` view or `INDEX.md`, database mutation, Company
Bank integration, a live model call, a pilot of any size, batch rendering, renderer
re-selection, template geometry changes, RenderCV work, or any dependency addition.

## 11. Acceptance criteria

- `render_doc_from_draft` is pure and fails closed on unknown ids, missing owners,
  dropped bullets, emphasis mismatch, illegal section names, and fingerprint
  disagreement.
- A draft rendered through the LaTeX arm produces a PDF in which every bullet, skill
  term, identity field, section heading, and numeric token survives extraction.
- Every modified bullet's rendered line count is measured from real PDF geometry and
  checked against the ≤ 2 limit; the check is proven on a recorded two-line fixture
  and a recorded three-line fixture.
- Emphasised substrings are proven to render bold.
- Horizontal and vertical page bleed, text collision, single-column layout, page
  count ≤ 1, file size ≤ 2.5 MB, charset, and heading order all gate publication.
- Every `RenderOutcomeKind` has a test; `l7_failure` publishes nothing.
- Re-running an already-published application is an idempotent no-op; a changed input
  fingerprint is a refusal, never an overwrite.
- `render_result.json` carries a real `render_line_check` verdict.
- No test invokes `pdflatex`; no code path imports `src.tailor.invoke`.
- Full suite green; `git diff --check` clean; DB SHA-256 unchanged at
  `a9966f4afa4771b61e5b1838c9930e4c64062dc9d85d6fbb49cef17447843ae1`.
