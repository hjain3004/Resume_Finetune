# M8N-0c — Atomic Keyword Placement Contract Repair

## 1. Context and Problem Statement
M8N-0 and M8N-0b implemented the file-fed tailoring lane, adding bounded length growth for S3 bullet edits. However, live benchmarks revealed a cross-stage contract defect regarding compound requirements (e.g., "data structures, algorithms, and distributed systems"). S1 extracts this as one term. S2 evaluates and splits it (validating baseline coverage), but S3 and G1 treat it inconsistently. G1 L3 demands the verbatim compound phrase in both a bullet and Skills. S3 either fails to place it or trips the uncited-vocabulary fabrication guard. The result is either a vacuous tailoring run (zero edits) or a rejected resume.

## 2. Design Goals
1. **Centralize atomic requirement parsing:** A single deterministic parser across S1, S2, S3, and G1 that splits compound terms into atomic components while preserving the exact quote.
2. **Deterministic Placement:** Every covered atomic term must appear exactly in ≥1 mapped bullet and the Skills section. S3 and G1 must enforce this deterministically.
3. **No Vacuous Success:** If S2 finds no valid tailorable coverage, the pipeline halts with `NO_TAILORABLE_COVERAGE`.
4. **Length and Fabrication Consistency:** Both S3 and G1 must use the exact same length-allowance rule (`max(len(t))`) without weakening the fabrication guard.

## 3. Component Fixes

### 3.1 Centralized Atomic Parsing
Create `src/tailor/requirement_terms.py` containing a function that splits compound terms using commas, semicolons, slashes, "and", and "or". Order, casing, and exact substring matching are preserved. Empty components and normalized duplicates are rejected. All stages (S1, S2, S3, G1) use this helper.

### 3.2 S1 Repair
Normalize S1 outputs dynamically by splitting compound terms into atomic `Requirement` objects. Prompt update: Request the model to emit one atomic requirement per entry.

### 3.3 S2 Repair
S2 evaluates atomic terms. A term is covered only if at least one cited selected bullet has an exact keyword hit. Baseline-only terms without bullet evidence must be marked as gaps. `do_not_claim` terms are blocked. Prompt update: Change "prefer gap" to "use gap" for baseline-only requirements without bullet evidence.

### 3.4 S3 and G1 Alignment
- S3 prompt receives a deterministic `placement_requirements` projection showing exactly what needs dual-placement.
- S3 and G1 use a shared placement/normalization helper.
- G1 L3 enforces atomic placement rules (at least once in a mapped bullet, at least once in Skills, ≤ 4 document-wide occurrences, top 5 covered terms occur 2-3 times).
- Both use the shared length allowance helper: `max(len(term) for term in edit.motivating_terms)`.

### 3.5 Pipeline Halt
If S2 produces zero evidence-backed covered terms (and not all are already dual-placed), raise `NO_TAILORABLE_COVERAGE`. Do not call S3, G2, or render.

## 4. Prompt Modifications
Changes are protected and will be requested explicitly.
- **S1:** Request one atomic requirement per entry.
- **S2:** "use gap" instead of "prefer gap" for baseline-only requirements without bullet evidence.
- **S3:** Demand all missing placements, smallest substitution, forbid unrelated rephrasing.

## 5. Testing
Add tests for S1 (atomic expansion), S2 (baseline gaps, independent coverage), S3 (placement logic, length allowance, empty/missing failures), G1 (atomic placement enforcement), and the full pipeline halt mechanism.
