# M8 item 3 — Tailor and Critic (design)

Status: approved, not implemented
Date: 2026-07-30
Phase: 3 (M8 Tailoring), item 3

## 1. Context

This design defines the architecture for the Phase 3 tailor (S1->S3) and critic (G2). To prevent LLM hallucinations, fabrication, and "slop", the tailor does not generate prose for the resume bullets. It is restricted to a structural output where it selects pre-authored phrasing from the master profile. 

The tailor's single prose authoring surface is the skills section, which is subjected to strict deterministic editing budgets and prohibited-word lists. A subsequent critic pass ensures stylistic alignment and quality.

## 2. File Contract & Schema (`config/tailored_schema.json`)

The tailor outputs a structural JSON document conforming to `config/tailored_schema.json` (to be validated by `src/audit_schema.py`). 

**Output Shape:**
- `base_variant`: String (e.g., "backend", "ml").
- `reasoning`: 2-4 sentences explaining the strategy (satisfying the S0 Positioning brief).
- `skills`: Object containing string arrays (e.g., `{"languages": ["Python", "Go"], ...}`). **This is the ONLY prose the tailor is allowed to author.**
- `projects`: Ordered list of objects containing `project_id`.
  - Inside each project, an ordered list of bullets containing:
    - `bullet_id`: Must match a valid bullet in the master profile.
    - `phrasing_tier`: "long", "medium", or "short".
    - `motivating_jd_quote`: Optional verbatim phrase from the JD justifying this inclusion.
    - `proposed_rewrite`: Optional string. If the tailor feels the bullet lacks a critical keyword, it suggests it here. *The wrapper NEVER renders this into the patched resume; it is surfaced only as a request in the human review packet.*
- `experience`: Ordered list following the exact same structure as projects.

## 3. Wrapper Responsibilities

The Python wrapper manages the LLM invocations and file I/O (mirroring `scripts/score_batch.py`):
1. Prompts the tailor with the JD and master profile projections (`for_tailoring`).
2. Validates the JSON output against `config/tailored_schema.json`.
3. **Change List Derivation**: Structurally compares the tailor's selection against the original `base_variant`'s default. The wrapper generates the "location / before / after / motivating JD phrase" change list automatically. The tailor's explicit output of changes is not trusted.
4. **Hydration**: Resolves text by looking up `(bullet_id, phrasing_tier)` in the master profile.
5. **Enforce `do_not_claim`**: Validates every term in the tailor's `skills` block against the master profile's `do_not_claim` list. Any hit is a hard failure (Lint L6).
6. **Enforce Blocked Claims**: Explicitly rejects any `bullet_id` from the tailor whose `claim_type` is in `BLOCKED_CLAIM_TYPES`.

## 4. Gate 1 (Lint) & Edit Budget

The edit budget and ATS arithmetic rules are shifted from the LLM critic to deterministic Python code.

### 4.1 Selection Budget (Structural)
- **Projects**: At most one `project_id` may be swapped compared to the chosen `base_variant`'s default. Reordering and changing `phrasing_tier` within projects are permitted freely.
- **Experience (Immutable)**: Every `experience_id` from the base variant MUST appear in reverse-chronological order. Output missing an `experience_id` is a hard rejection. Only bullet selection, ordering, and phrasing tier vary within them.
- **Flagship Rule**: No filler bullet may precede a flagship bullet within the same project/experience.

### 4.2 Wording Budget (Token-Level)
- Applies **exclusively** to the `skills` block text authored by the tailor.
- The tailor's skills block is normalized (casefolded, whitespace collapsed, word-edge punctuation stripped).
- Token-level distance is computed using `difflib.SequenceMatcher(autojunk=False)` against the base variant's skills block.
- **Distance Formula**: `replace(max(i2-i1, j2-j1)) + delete(i2-i1) + insert(j2-j1)`.
- **Budget Check**: `Distance / len(base_skills_block_tokens) <= 0.15`. The skills line may shift by at most 15% of its original token count.

### 4.3 Countable Lints
- **Keyword Stuffing**: Ensures no term appears > 4x in the document.
- **Dual Placement**: Every "must-have" JD keyword must appear in the skills section AND in $\ge 1$ bullet.

## 5. Gate 2 (Critic Pass)

A separate, headless Claude invocation that does **not** see the structural JSON or the tailor's reasoning. 
- **Input**: The fully hydrated plain-text "patched resume", the JD, `config/banned_words.txt`, `config/taste.md`, and the rubric.
- **Revised Rubric**:
  - **R1 (Fabrication)**: Explicitly rescoped to apply *only* to the skills block. (All other bullet text is deterministically sourced, rendering bullet fabrication impossible by design).
  - **R2 (Voice)**: Checks for stylistic violations (banned vocabulary, generic LLM phrasing, lack of XYZ formatting).
  - **R6 (Smell)**: Checks for "generic AI resume" templates.
- **Loop**: Maximum 2 revision rounds. If unresolved issues remain, the wrapper generates the final review packet with open flags appended.

## 6. Config Additions
- `config/banned_words.txt`: Seeded with vocabulary from the methodology (spearheaded, passionate, delve, etc.).
- `config/taste.md`: A user feedback ledger. Seeded with a header comment indicating the expected `YYYY-MM-DD: lesson` format.
