# M8 item 3 — Tailor and Critic (plan)

Status: not implemented
Date: 2026-07-30
Phase: 3 (M8 Tailoring), item 3

## Overview

Implement the deterministic wrapper, the Tailor (S1->S3), and the Critic (G2) following the `2026-07-30-m8-tailor-critic-design.md` spec. Work is entirely driven by test-driven development (TDD), one task per commit. 

## Task List

### Task 0: Create Configuration Seed Files
1. Create `config/banned_words.txt` containing the seed vocabulary from the methodology (e.g., spearheaded, passionate, results-driven, dynamic, synergy, leverage, cutting-edge, etc.).
2. Create `config/taste.md` with a leading header comment explaining the expected `YYYY-MM-DD: lesson` format.
3. Commit `feat(m8): create tailor config files`.

### Task 1: Tailored Schema and Validation
1. Create `config/tailored_schema.json` with the structural constraints outlined in the design (`base_variant`, `reasoning`, `skills`, `projects`, `experience`).
2. Update `src/audit_schema.py` to register and validate against this new schema file.
3. Write a unit test `test_tailored_schema.py` with passing and failing fixtures (e.g., missing `experience` block, missing `phrasing_tier`, extraneous prose in projects).
4. Commit `feat(m8): add tailored schema definition and validation`.

### Task 2: Gate 1 Lints - Wording Budget & Skills Guard
1. In `src/tailor/lint.py`, implement `check_wording_budget(base_skills, tailored_skills)`.
   - Normalize strings (casefold, strip word-edge punctuation, collapse whitespace).
   - Split by whitespace into tokens.
   - Use `difflib.SequenceMatcher(autojunk=False)` to calculate distance: `replace(max(i2-i1, j2-j1)) + delete(i2-i1) + insert(j2-j1)`.
   - Denominator: `len(base_skills_tokens)`. Ensure ratio $\le 0.15$.
2. Implement `check_skills_do_not_claim(tailored_skills, master_profile_dnc)`.
3. Write unit tests for both functions with passing and failing cases (including budget overrun).
4. Commit `feat(m8): implement Gate 1 wording budget and do_not_claim lints`.

### Task 3: Gate 1 Lints - Selection Budget & Structural Guards
1. In `src/tailor/lint.py`, implement structural lints against the tailor's output:
   - `check_selection_budget`: Ensure $\le 1$ project swap compared to base variant.
   - `check_experience_immutable`: Verify every `experience_id` from the base variant is present in reverse-chronological order.
   - `check_flagship_ordering`: Verify no filler bullet precedes a flagship bullet.
   - `check_blocked_claims`: Reject any `bullet_id` with a `claim_type` in `BLOCKED_CLAIM_TYPES`.
2. Write unit tests with passing and failing fixtures.
3. Commit `feat(m8): implement Gate 1 selection budget and structural lints`.

### Task 4: Gate 1 Lints - Countable JD Rules
1. Implement `check_keyword_frequency(hydrated_text)`. Ensure no word/term occurs > 4x.
2. Implement `check_dual_placement(must_have_keywords, skills, hydrated_bullets)`.
3. Write unit tests.
4. Commit `feat(m8): implement Gate 1 countable JD rules`.

### Task 5: Hydration and Diff Generation
1. In `src/tailor/wrapper.py`, implement the function `hydrate_tailor_draft(tailor_json, master_profile)` that looks up `(bullet_id, phrasing_tier)` and returns the plain-text resume.
2. Implement `derive_change_list(base_variant, tailor_json)` to output the location, before, after, and motivating JD phrase structurally.
3. Write tests for both hydration and change list derivation.
4. Commit `feat(m8): implement resume hydration and change list derivation`.

### Task 6: Wrapper Orchestration (S1->S3)
1. In `src/tailor/wrapper.py`, implement `run_tailor(jd_text, master_profile)`.
   - Construct prompt (incorporating `for_tailoring` projection).
   - Call Claude via `subprocess.run(["claude", "-p", prompt])`.
   - Parse JSON output.
   - Run Gate 1 Lints. Return errors or the hydrated draft.
2. Create mocked tests mimicking Claude's response.
3. Commit `feat(m8): implement tailor wrapper orchestration`.

### Task 7: Critic Wrapper (G2)
1. In `src/tailor/wrapper.py`, implement `run_critic(hydrated_text, jd_text, banned_words, taste)`.
   - Pass rubric R1, R2, R6.
   - Parse JSON output (verdict or issues).
2. Implement the `tailor_loop` that orchestrates max 2 revision rounds between the Tailor and Critic.
3. Commit `feat(m8): implement critic wrapper and revision loop`.

### Task 8: Integration and Acceptance
1. Add an integration test in `tests/test_tailor_integration.py` that mocks Claude responses to simulate a full successful pass, a lint failure, and a critic round rejection leading to success.
2. Run full `pytest -q` suite.
3. Commit `feat(m8): add integration tests for tailor critic`.
