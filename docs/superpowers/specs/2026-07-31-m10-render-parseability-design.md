# M10 — Rendering decision gate + parseability CI (design)

Status: approved, not implemented
Date: 2026-07-31
Phase: Upgrades (M9–M12), M10. **Blocks M8's render step.**

## 1. Context

`docs/UPGRADE_PLAN.md:79` makes M10 a hard prerequisite for M8's render step. Two things
must come out of this milestone:

1. A **decision**, recorded in `DECISIONS.md`, about which renderer produces the PDF.
2. An **L7 parseability gate** that is adopted *regardless* of which renderer wins.

The decisive constraint is already in the repo and is not currently enforced anywhere.
`config/master_profile.yaml:44-63` declares an `ats:` policy block — single column,
`contact_in_body: true`, no tables/text boxes/graphics, a four-entry `headings_whitelist`,
`charset_policy: ascii_strict` with an explicit `forbidden_chars` list, `max_file_size_mb:
2.5`, and a `filename_pattern`. The comment on line 42 already asserts the intended
architecture: *"The renderer reads these; the audit suite asserts them."* Today nothing
reads them and nothing asserts them.

So M10 is not primarily a renderer beauty contest. It is the milestone that turns the
declared `ats:` policy into a mechanically enforced contract, and picks a renderer that can
satisfy it. The bake-off is a means to that end, not the point.

### 1.1 What M10 is NOT

- Not M8's render step. M10 produces the renderer decision, the IR, and the gate. Wiring
  the tailor's structural output through to a delivered application PDF stays in M8.
- Not a change to G1 (L1–L6). Those lints operate on the pre-render draft and are
  untouched. L7 is a distinct, post-render gate over a *rendered artifact*.
- Not a scoring, discovery, or DB change. M10 writes no SQLite.

## 2. Approved dependency expansion

`CLAUDE.md` prime directive 4 caps runtime dependencies. On 2026-07-31 the user approved
three additions for M10. They are **not** all adopted at the same tier — approval to
evaluate is not approval to depend on at runtime:

| Dependency | Tier | Role |
|---|---|---|
| `pdfminer.six` | **Hard runtime dep** | L7 Tier A text + layout extraction. Chosen over `pypdf` because L7 must detect *reading order and column* failures, which needs glyph bounding boxes (`LTTextBox.bbox`); `pypdf` exposes text without reliable geometry. |
| RenderCV (+ Typst) | **Bake-off only, adoption conditional** | Arm (b) of the bake-off. Becomes a runtime dep only if it wins §4.4. |
| OpenResume parser (Node) | **Opt-in oracle, never a test dep** | Tier B fidelity check. See §5.3. |

**Node must never become required to run `pytest -q`.** The repo is pure Python and
`CLAUDE.md` requires tests never touch the network. Tier B is therefore gated behind a
pytest marker and skipped by default; a contributor without Node gets a green suite.

## 3. The intermediate representation (the load-bearing decision)

Both bake-off arms consume one immutable IR, `RenderDoc`. This is what makes the renderer
decision **reversible** and keeps the bake-off honest — swapping renderers must not
re-open the mapping work, and neither renderer gets to define the data model in its own
image.

The four resume sections genuinely have different shapes (projects carry no date,
experience carries no location, skills is a category map, not a list of entries), so the IR
models them as distinct typed fields rather than forcing a uniform `sections` list.

```python
@dataclass(frozen=True)
class RenderBullet:
    bullet_id: str          # G0 traceability; stripped from rendered output
    text: str               # resolved from (bullet_id, phrasing_tier)

@dataclass(frozen=True)
class RenderEntry:
    entry_id: str           # project_id, experience_id, or institution slug
    heading: str
    subheading: str
    date_range: str = ""
    location: str = ""
    bullets: tuple[RenderBullet, ...] = ()

@dataclass(frozen=True)
class RenderDoc:
    identity: dict[str, str]
    education: tuple[RenderEntry, ...]
    experience: tuple[RenderEntry, ...]
    projects: tuple[RenderEntry, ...]
    skills: dict[str, tuple[str, ...]]
    section_order: tuple[str, ...]   # permutation of ats.headings_whitelist
    ats: dict[str, Any]
```

`section_order` exists so L7's heading check can be **order-aware** without the renderer
having to report its own layout.

`RenderDoc` carries `bullet_id` all the way to the renderer boundary. The renderer strips
ids at emit time; L7 then verifies each bullet's *text* survived. This is how G0
traceability (`TAILORING_METHODOLOGY.md:172`) survives into the PDF, per
`UPGRADE_PLAN.md:99`.

### 3.1 Mapping

`build_render_doc(profile: MasterProfile, base_variant: str, tier_overrides: dict[str, str]
| None) -> RenderDoc` is pure and deterministic. It resolves `bullet_order` from the named
base variant via the existing loader (`MasterProfile._ordered_bullets`), picks the phrasing
tier, and groups bullets under their owning project/experience.

Field mapping is fixed by what the loader actually exposes (`src/profile.py:141-264`):

| IR field | Education (`dict`) | `Experience` | `Project` |
|---|---|---|---|
| `entry_id` | slugified `institution` | `id` | `id` |
| `heading` | `institution` | `employer` | `display_title` |
| `subheading` | `degree` | `title` | `tech_line` |
| `date_range` | `display_date` | `display_date` | `""` (projects carry no date) |
| `location` | `location` | `""` (no field exists) | `""` (no field exists) |
| `bullets` | `()` | from `bullet_order` | from `bullet_order` |

**Phrasing tier selection.** `Phrasings.short` is the only guaranteed tier (`medium` and
`long` are `str | None`, `src/profile.py:142-145`). Resolution is: an explicit
`tier_overrides[bullet_id]` if present and non-`None` on that bullet, else `medium`, else
`short`. Requesting a tier that is `None` on that bullet is a hard error, not a silent
downgrade — a silent downgrade would let M8's tailor believe it selected a phrasing it did
not get.

It is a **hard error** — not a warning — if a section name is absent from
`ats.headings_whitelist`, or if a bullet id is unresolvable. Silent degradation here would
produce a resume missing content, which is the exact failure mode L7 exists to catch.

## 4. The bake-off

### 4.1 Blocking input

Arm (a) requires the user's interview-tested LaTeX source, which is **currently absent from
the repo** — `profile/` holds six PDFs and no `.tex`/`.cls`. The user is exporting it from
Overleaf to `profile/template/`. Until it lands, arm (a) cannot run.

Arm (b) and all of §5 (the L7 gate) are **independent of this** and proceed regardless.
This is deliberate: the milestone's durable deliverable is the gate, and it must not be
held hostage to an export.

### 4.2 Arm (a) — existing LaTeX

`RenderDoc` → string templating over the user's `.tex` (no new templating dependency;
`string.Template` over a tokenized copy of the user's template) → `pdflatex`. LaTeX is
either installed on the user's machine or it is not; if absent, arm (a) is reported as
un-runnable rather than silently skipped.

### 4.3 Arm (b) — RenderCV

`RenderDoc` → RenderCV YAML → Typst → PDF.

### 4.4 Decision criteria (in precedence order)

1. **Visual acceptability to the user — hard gate, human judgment.** The user's template is
   interview-tested. `UPGRADE_PLAN.md:90` is explicit that if LaTeX wins on visuals, we
   keep LaTeX and take only the L7 gate, and that this is a fully acceptable outcome.
2. **L7 parse fidelity** (§5), scored identically for both arms.
3. **Pipeline fit** — diffability, ids-as-keys, reproducibility of byte-identical output.

An agent cannot decide criterion 1. The plan therefore contains an explicit **human
checkpoint** that halts execution and presents both PDFs.

## 5. L7 — the parseability gate

**Formulation:** L7 compares the `RenderDoc` (what we intended to say) against the parsed
PDF (what an ATS actually sees). Every assertion is a statement about survival of intended
content through the render→parse round trip.

This is the point of the gate: a term can pass L3's keyword bounds in the draft and still
be invisible to the recruiter's ATS because it landed in a text box, a second column, or a
ligature. `UPGRADE_PLAN.md:98` names this "a delivery failure invisible to all other
gates."

### 5.1 Tier A — deterministic, in-process, always runs

Pure `pdfminer.six`. Returns `list[str]` violations, matching the convention already
established in `src/tailor/lint.py` (every `check_*` returns a violation list; the caller
aggregates). Assertions:

| Check | Rule |
|---|---|
| `identity` survival | name, phone, email, location each appear in extracted text |
| contact in body | contact block's y-coordinate is inside the main text frame, not in a header/footer band — enforces `ats.layout.contact_in_body` (a known Greenhouse parse failure) |
| single column | all text boxes on a page share one dominant x-band; a bimodal x distribution is a violation — enforces `ats.layout.columns: 1` |
| section headings | every name in `RenderDoc.section_order` appears, in that order, and each is in `ats.headings_whitelist` |
| bullet survival | every `RenderBullet.text` across education/experience/projects appears in extracted text after whitespace normalization |
| skills survival | every term in `RenderDoc.skills` appears |
| charset | zero occurrences of `ats.forbidden_chars` — enforces `charset_policy: ascii_strict` |
| file size | PDF ≤ `ats.max_file_size_mb` |

Reading order matters, so extraction preserves document order and comparisons are
order-aware for headings.

### 5.2 Fixtures

Per `CLAUDE.md`, tests never touch the network and fixtures are committed. Two PDFs are
recorded once and committed as binary:

- `tests/fixtures/render/good_single_column.pdf` — the winning renderer's real output; must PASS.
- `tests/fixtures/render/bad_two_column.pdf` — deliberately corrupted (`\twocolumn` or a
  tabular layout); must FAIL, and must fail on the *column* and *bullet survival* checks
  specifically, not merely fail somehow.

Asserting *which* check fires is what makes the acceptance criterion in
`UPGRADE_PLAN.md:103` meaningful rather than a tautology.

### 5.3 Tier B — OpenResume oracle, opt-in

Tier A encodes our *belief* about what breaks ATS parsing. Tier B checks that belief
against a real resume parser. It runs under `@pytest.mark.oracle`, deselected by default,
and is invoked manually during the bake-off and thereafter when Tier A's heuristics are
changed. A Tier A/Tier B disagreement is a finding to investigate and record — it means our
heuristic is miscalibrated — not an automatic failure.

## 6. File structure

| Path | Responsibility |
|---|---|
| `src/render/__init__.py` | package marker |
| `src/render/model.py` | the `RenderDoc` IR dataclasses (§3), no I/O |
| `src/render/mapping.py` | `build_render_doc()` — pure, profile → IR (§3.1) |
| `src/render/latex.py` | arm (a) emitter + `pdflatex` invocation |
| `src/render/rendercv.py` | arm (b) emitter + RenderCV invocation |
| `src/render/parse.py` | `pdfminer.six` extraction → `ParsedPdf` (text + boxes + geometry) |
| `src/render/l7.py` | the `check_*` gate functions (§5.1), pure over `(RenderDoc, ParsedPdf)` |
| `scripts/render_bakeoff.py` | operator script producing both PDFs + a comparison report |

`src/tailor/lint.py` stays dependency-free and is not modified. L7 lives beside the
renderer because it needs PDF parsing; it borrows lint.py's return convention so the two
read as one family.

## 7. Acceptance

Per `UPGRADE_PLAN.md:103`, plus the dependency constraint:

- [ ] Bake-off artifacts produced for every runnable arm; decision recorded in `DECISIONS.md`.
- [ ] L7 Tier A passes on the real template's PDF and fails on the two-column fixture, with
      the *specific* expected checks firing.
- [ ] Render mapping round-trips one golden application with zero manual edits.
- [ ] `pytest -q` green with **no Node installed** and Tier B deselected.
- [ ] `CLAUDE.md` prime directive 4 dependency list updated to match what was actually adopted.

## 8. Open questions for the user

1. **LaTeX export** — arm (a) is blocked until `profile/template/` contains the `.tex`
   (and any `.cls`). If the export does not happen, M10 proceeds with arm (b) + L7 only,
   and the renderer decision is deferred.
2. **`pdflatex` availability** — unverified on this machine at design time. If absent, arm
   (a) is un-runnable even with the source, and that fact gets recorded rather than worked
   around.
