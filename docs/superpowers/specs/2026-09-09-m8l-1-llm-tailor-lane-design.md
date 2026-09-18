# Design Document: LLM-First Tailoring Lane (M8L-1)

## 1. Revised File-Level Design

The new LLM-first lane is isolated in its own package to strictly enforce the four-call budget, deterministic validation, and isolation from the legacy stage chain. 

**New package: `src/llm_tailor/`**
- `__init__.py`: Package entry point.
- `schemas.py`: Pydantic models defining the strict contracts for Draft, Audit, Repair, and Re-audit model interactions.
- `normalization.py`: Deterministic string manipulation functions for JD span and numeric token validation.
- `validators.py`: All deterministic checks (schema validity, span resolution, uniqueness, metric verification, L7 compilation, page fill).
- `lane.py`: The single-pass control plane that orchestrates the drafting, auditing, repairing, and rendering sequence.
- `cli.py`: The CLI entry point that enforces explicit absolute paths (`--db`, `--output-dir`) and wires up the dependencies.

## 2. Model Interactivity Schemas

**Important**: Pydantic covers schema validation only. Every model in the lane must set `model_config = ConfigDict(strict=True, extra="forbid")` to strictly reject coercion (`"3" -> int`, `True -> int`) and extra fields. 

Hand-written deterministic validators will enforce the following domain constraints:
- Quote is a substring of its cited span, after the documented normalization.
- `source_span_id` and every `evidence_ids` entry resolve.
- No `do_not_claim` term anywhere (e.g., `Kubernetes` never appears).
- No numeric token absent from the cited evidence, after documented normalization.
- Repair preserves index, entry ID, section, evidence IDs, requirement IDs, ordering.
- All seven Amdocs IDs accounted for; none both selected and omitted.
- Audit covers every drafted bullet exactly once, indices complete/ordered/unique.
- Colon-led fragments and semicolon chains rejected (those two patterns specifically, not all colons and semicolons).
- Emphasis stripped before numeric, duplication, and banned-term checks.
- Page fill and skills section constraints (detailed in Section 8).

```python
from pydantic import BaseModel, ConfigDict
from typing import Literal

# --- 1. Draft Phase ---
class Requirement(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    id: str
    source_span_id: str
    quote: str
    requirement: str
    importance: Literal["must_have", "nice_to_have"]
    evidence_ids: list[str]

class DraftedBullet(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    id: str
    entry_id: str
    section: str
    text: str
    supported_requirement_ids: list[str]
    evidence_ids: list[str]

class DraftResponse(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    requirements: list[Requirement]
    bullets: list[DraftedBullet]
    omitted_evidence_ids: dict[str, str]

# --- 2. Audit & Re-Audit Phases ---
class AuditBulletResult(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    id: str
    evidence_ids: list[str]
    accepted: bool
    rejection_reason: str | None
    fidelity_ok: bool
    coherence_ok: bool
    relevance_ok: bool
    readability_ok: bool

class AuditResponse(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    results: list[AuditBulletResult]

# --- 3. Repair Phase ---
class RepairedBullet(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    id: str
    text: str

class RepairResponse(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    repaired_bullets: list[RepairedBullet]
```

## 3. Exact JD-Span Normalization Rules

Before being passed to the model, the raw job description is deterministically split into stable spans:

1. **Decode**: Decode JD text as UTF-8.
2. **Unicode Normalization**: Apply `NFKC` unicode normalization to the entire text.
3. **Punctuation Standardization**: Replace all stylistic apostrophes/quotes (`’`, `‘`, `´`) with `'` (U+0027) and (`“`, `”`) with `"` (U+0022).
4. **Spacing Collapse**: Replace all non-breaking spaces, zero-width spaces, and consecutive whitespace sequences (spaces, tabs) with a single space.
5. **Span Splitting**: Split the normalized text into semantic blocks by paragraph breaks (`\n\n+`) and standard list item markers (lines starting with `-`, `*`, `•`, or `\d+\.`).
6. **Trim**: Strip leading and trailing whitespace from each extracted span and assign a deterministic ID (e.g., `jd_001`).

When validating the `quote` returned by the model, the validator applies steps 2, 3, 4, and 6 to the raw quote before performing a strict substring check (`normalized_quote in normalized_span`).

## 4. Exact Numeric-Token Normalization Rules

To prevent keyword inflation while maintaining robustness against stylistic variations (e.g., `~60%` vs `60` vs `roughly 60`), we extract and compare base digit sequences:

1. **Comma Removal**: Strip all commas that appear strictly between digits (e.g., `1,000` → `1000`).
2. **Symbol Stripping**: Remove all currency symbols (`$`, `€`, `£`, etc.) and percentage signs (`%`).
3. **Approximation Stripping**: Remove approximation words and symbols (`~`, `<`, `>`, `+`, `roughly`, `approximately`, `around`, `over`, `up to`, `nearly`).
4. **Digit Extraction**: Extract all remaining contiguous digit sequences (e.g., using `\b\d+(?:\.\d+)?\b`).
5. **Validation**: Ensure every digit sequence extracted from the drafted bullet exists in the set of digit sequences extracted from its cited canonical evidence.

## 5. Database and Output Isolation Design

- **Absolute Paths Only**: The CLI requires explicit `--db` and `--output-dir` arguments. Writes to the `data/` symlink are prohibited.
- **Read-Only Database**: SQLite access uses `src.db.get_readonly_connection(args.db)`. The lane does not mutate job rows or scoring records.
- **CWD-Assuming Modules**: The only reused module that assumes CWD is `src/llm_trace.py` (which defaults to `Path("data/traces")`). The new lane bypasses this by explicitly passing `trace_dir=args.output_dir / "traces"` on every model invocation.
- **Testing**: Test suites operate entirely within `tmp_path` fixtures using ephemeral SQLite databases, ensuring zero cross-talk with the real repository.

## 6. Protected-Document Diffs

### `CLAUDE.md`
```diff
--- CLAUDE.md
+++ CLAUDE.md
@@ -16,7 +16,7 @@
 1. **The docs are authoritative.** Read `docs/ARCHITECTURE.md` before writing code. If code
    and docs disagree, the docs win. If the real world and the docs disagree (a site changed,
    an endpoint differs), stop and ask the user; record approved deviations in
    `docs/DECISIONS.md`.
 2. **One milestone at a time.** Never start milestone N+1 in the same session as N.
 3. **Idempotency is sacred.** Any change that could make a second identical run mutate the DB
    is a bug, full stop.
-4. **No unapproved dependencies.** The currently approved list is: requests, trafilatura, PyYAML, pytest, crawl4ai (M6.5 tier-2 resolver), pdfminer.six (M10 L7 gate). RenderCV/Typst are bake-off-only and become runtime deps only if adopted by the M10 decision; Node/OpenResume is an opt-in test oracle and must never be required by pytest -q.
+4. **No unapproved dependencies.** The currently approved list is: requests, trafilatura, PyYAML, pytest, crawl4ai (M6.5 tier-2 resolver), pdfminer.six (M10 L7 gate), pydantic (M8L-1 strict validation). RenderCV/Typst are bake-off-only and become runtime deps only if adopted by the M10 decision; Node/OpenResume is an opt-in test oracle and must never be required by pytest -q.
    Ask before adding anything else.
```

### `AGENTS.md`
```diff
--- AGENTS.md
+++ AGENTS.md
@@ -17,9 +17,9 @@
 2. **One milestone at a time.** Never start milestone N+1 in the same session as N.
 3. **Idempotency is sacred.** Any change that could make a second identical run mutate the DB
    is a bug, full stop.
-4. **No unapproved dependencies.** The currently approved list is: requests, trafilatura,
-   PyYAML, pytest, crawl4ai (M6.5 tier-2 resolver; M9D may evaluate bounded deep crawling),
-   playwright (company-bank `verify-sources --render`; see below).
+4. **No unapproved dependencies.** The currently approved list is: requests, trafilatura,
+   PyYAML, pytest, crawl4ai (M6.5 tier-2 resolver; M9D may evaluate bounded deep crawling),
+   playwright (company-bank `verify-sources --render`; see below), pydantic (M8L-1 strict validation).
    Crawlee Python and Apify integrations are design candidates, not approved runtime
    dependencies. Ask before adding either or anything else, including BeautifulSoup.
```

### `docs/ARCHITECTURE.md`
```diff
--- docs/ARCHITECTURE.md
+++ docs/ARCHITECTURE.md
@@ -107,6 +107,11 @@
 │   │   ├── tailored.py        # M8P-5: draft-to-RenderDoc projection and fingerprint binding
 │   │   ├── lines.py           # M8P-5: PDF line- and character-level geometry
 │   │   └── l7.py              # M10/M8P-5: structural and tailored L7 validation
+│   ├── llm_tailor/            # M8L-1: new LLM-first tailoring lane
+│   │   ├── __init__.py
+│   │   ├── schemas.py         # draft, audit, repair, re-audit contracts
+│   │   ├── validators.py      # deterministic enforcement
+│   │   └── lane.py            # isolated control plane workflow
 │   ├── tailor/                # M8: Tailoring stages, G1/G2 critic, and publication
 │   │   ├── publish.py         # M8P-5: atomic per-application publication and commit marker
```

### `docs/TAILORING_METHODOLOGY.md`
```diff
--- docs/TAILORING_METHODOLOGY.md
+++ docs/TAILORING_METHODOLOGY.md
@@ -99,6 +99,19 @@
 
 ## 3. Per-application workflow
+
+**Amendment (2026-09-09, M8L-1).** A separate LLM-first lane exists
+alongside the staged chain below. It normally uses two model calls:
+evidence-grounded drafting and independent audit. When the audit rejects
+one or more bullets, the lane may make one targeted repair call followed
+by one re-audit of only the repaired bullets, for a maximum of four model
+calls. A failed re-audit halts for human review.
+
+Code in this lane enforces only objective properties, including schema
+validity, resolvable source spans and evidence IDs, prohibited claims,
+unsupported numeric tokens, repair scope, and post-render L7 checks.
+Editorial judgment belongs to the independent audit model, never to a
+regex or test-specific exception. The existing staged chain remains
+available and its stage code is not shared with the new lane.
 
 ```
 JD (jd_quality='ats' REQUIRED)
```

### `docs/DECISIONS.md`
```diff
--- docs/DECISIONS.md
+++ docs/DECISIONS.md
@@ -1,3 +1,21 @@
 # System Decisions
 
+## 2026-09-10: M8L-1 — Pydantic promoted to a direct dependency & LLM-first tailoring lane
+
+- **Context:** A new dedicated `llm_tailor` package is being created to provide an LLM-first, strict-budget drafting lane. It enforces deterministic constraints outside the model and acts on a strict four-call limit (Draft → Audit → Repair → Re-Audit). `pydantic>=2.0` was already installed in the branch, pulled in transitively by `crawl4ai`, but was not declared in the approved dependency lists.
+- **The coupling:** The new LLM-first tailoring lane relies on Pydantic to strictly enforce model output schemas. Retiring Crawl4AI is a stated goal of the Firecrawl design. Had Crawl4AI been removed with this coupling undocumented, the tailoring lane would have broken silently.
+- **Decision:** Pydantic is now a directly approved dependency in `AGENTS.md` and `CLAUDE.md`, independent of Crawl4AI. Every model in the lane must set `model_config = ConfigDict(strict=True, extra="forbid")` to prevent silent coercion (e.g. coercing `True` or `"3"` to an `int`).
+- **Unchanged:** The existing deterministic stage chain (`tailor`) remains unmodified. Pydantic covers schema validation only; hand-written validators still enforce rules like JD quote exact-substring matches, evidence resolution, absence of banned terms, numeric token matching, repair scope, and page fill constraints.
+
```

## 7. Exact `config/taste.md` Diff

```diff
--- config/taste.md
+++ config/taste.md
@@ -4,3 +4,11 @@
 YYYY-MM-DD: lesson
 -->
 
+2026-09-09:
+- Continuous coherent bullets; compressed STAR/XYZ format.
+- No colon-led fragments.
+- No semicolon chains.
+- No architecture dumps.
+- No arbitrary bullet quota.
+- Amdocs is prioritized as primary professional experience.
+- Evidence strength and role relevance determine selection.
```

## 8. Named Page Fill & Profile Porting Validators

The following new deterministic validators will be enforced:

**(a) `validate_page_fill_above_97_percent`:** Measured topmost-to-bottommost text extent over page height, this must be > 97% after render. The threshold is deliberately higher than previous profiles. The lane must achieve this by selecting more evidence-backed bullets, never by tuning spacing.

**(b) `validate_skills_section_not_padded`:** Measure fill and cap the skills section independently. A padded skills line cannot be used to satisfy the overall fill check. The audit will actively reject skills-section keyword inflation.

**Approved Profile Diff Confirmation:**
The isolated diff from the quarantined directory (`/Users/himanshu_jain/aero/Resume_Finetune/job-pipeline`) has been verified to explicitly include all requested edits, and exclusively those edits:

| Bullet ID | Change Summary | Canonical Evidence Trace |
|---|---|---|
| **`am_b00_order_management_domain`** | Rewritten across `medium` and `short` tiers. (No `long` tier exists for this bullet). | `scope_line` names Order Management, Java, Spring Boot, Jenkins, OpenShift. |
| **`am_b01_dlq_consolidation`** | Rewritten across all 3 tiers (`long`/`medium`/`short`). | Interview prep doc DLQ section, migration runbook. |
| **`am_b02_row_level_entitlement`** | Rewritten across all 3 tiers. Inserted into the backend `bullet_order` at position 13. | Prep doc data fencing section. |
| **`am_b03_audit_trail`** | Rewritten across all 3 tiers. | Prep doc traceability section, Actor resolution. |
| **`am_b04_data_retention`** | Rewritten across all 3 tiers. | Prep doc purge and archive section. |
| **`am_b05_test_automation`** | Rewritten across all 3 tiers. | Prep doc testing section, WireMock scenarios. |
| **`am_b06_aws_ci_and_resilience`** | Rewritten across `medium` and `short` tiers. (No `long` tier exists for this bullet). | Maven profile updates, HELM value refactors. |
| **`cm_b1`** | Kept ownership framing but stripped numerical claims (20 REST controllers, 24 JPA entities, 30 Flyway migrations, and the `long` tier's 48 of 68 commits) across all 3 tiers. | `campus-marketplace` source files and `@RestController` counts. |
| **Global Evidence Check** | All `evidence:` fields across the profile remain unchanged. They correctly retain source numbers (e.g., "48 of 68 commits") as git-shortlog provenance. | Unchanged provenance fields. |

## 9. Test Matrix

The test suite will exercise the lane over four strictly isolated execution paths, plus an explicit structural regression test:

1. **Pass on first attempt**: Draft model provides bullets → Audit model accepts all bullets → Execution proceeds to render and post-render validation (L7, >97% fill).
2. **Repair success**: Draft model provides bullets → Audit model rejects at least one bullet → Repair model is called for rejected bullets, text updated → Re-audit model accepts repaired bullets → Execution proceeds to render.
3. **Repair failure (Halt)**: Draft model provides bullets → Audit model rejects at least one bullet → Repair model modifies rejected bullets → Re-audit model rejects repaired bullets again → Execution halts, writes findings to output directory, exits non-zero. **No rendering.**
4. **Invalid selection (Halt)**: Draft model selects evidence that is wrong (according to Audit model) → Audit model rejects selection → Execution halts for human review (no repair is attempted, because repair cannot change evidence selection).
5. **Pydantic Strictness Guard**: Explicitly assert that passing `"3"` or `True` to an integer field, or an undocumented extra field, fails validation against a representative model. This ensures `model_config = ConfigDict(strict=True, extra="forbid")` is never silently removed.

## 10. Confirmation

I confirm that **no implementation file has been changed in the clean worktree**. The worktree remains pristine on `aaefb15`. I await your final approval of this design document before writing any code.
