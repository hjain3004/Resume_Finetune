# Tailor2 Render-Measure-Expand-Compress Optimizer Specification & Evaluation Corpus

## 1. Executive Summary & Objective

This document defines the deterministic evaluation corpus, machine-readable fixture schema, and acceptance test scaffolding for the **Tailor2 Render-Measure-Expand-Compress Optimizer**.

In earlier phases, Tailor2 established:
1. Canonical master profile grounding and strict audit/provenance boundaries.
2. Semantic requirement interpretation and local/whole-résumé candidate ranking.
3. Unused-evidence tracking via an auditable reserve ledger.

This phase builds the evaluation harness for the visual and physical realization of the tailored résumé: **measuring compiled output, correcting geometric defects, expanding into available vertical whitespace with verified evidence, and safely compressing overflowing content while holding factual integrity invariant.**

No live provider or LLM calls are permitted. All fixtures, measurements, and tests are deterministic and reproducible.

---

## 2. Architecture: Render-Measure-Expand-Compress Loop

The optimizer executes an iterative loop bounded by strict iteration and provider budgets:

```
                  ┌─────────────────────────────────┐
                  │   Input Draft / Candidate       │
                  └────────────────┬────────────────┘
                                   │
                                   ▼
                  ┌─────────────────────────────────┐
                  │ 1. Compile & Render (LaTeX/PDF) │
                  └────────────────┬────────────────┘
                                   │
                                   ▼
                  ┌─────────────────────────────────┐
                  │ 2. Measure Geometry & Layout    │
                  │    - Page count & fill ratio    │
                  │    - Collisions (heading, date) │
                  │    - Overflow & orphan wraps    │
                  │    - Margins & min font size    │
                  │    - Readability density score  │
                  └────────────────┬────────────────┘
                                   │
         ┌─────────────────────────┴─────────────────────────┐
         │                                                   │
   [Clean Fit]                                         [Defect Found]
         │                                                   │
         ▼                                                   ▼
┌──────────────────┐                       ┌───────────────────────────────────┐
│ State: ACCEPTED  │                       │ 3. Evaluate Action Strategy       │
└──────────────────┘                       │    - Underfill  -> Expand         │
                                           │    - Overflow   -> Compress       │
                                           │    - Collision  -> Resolve        │
                                           └─────────────────┬─────────────────┘
                                                             │
                                   ┌─────────────────────────┴─────────────────────────┐
                                   ▼                                                   ▼
                    ┌──────────────────────────────┐                   ┌──────────────────────────────┐
                    │ Expansion Engine             │                   │ Compression Engine           │
                    │ - Query unused ledger        │                   │ - Swap shorter variants      │
                    │ - Pick highest value item    │                   │ - Tighten vertical spacing   │
                    │ - Block prohibited/filler    │                   │ - Preserve metrics (~40%)    │
                    │ - Roll back if overflows     │                   │ - Roll back if illegible     │
                    └──────────────┬───────────────┘                   └──────────────┬───────────────┘
                                   │                                                   │
                                   └─────────────────────────┬─────────────────────────┘
                                                             │
                                                             ▼
                                           ┌───────────────────────────────────┐
                                           │ 4. Safety & Invariance Gates      │
                                           │    - Factual metrics preserved?   │
                                           │    - Readability >= threshold?    │
                                           │    - Prior best-safe preserved?   │
                                           │    - Cycle detected via hash?     │
                                           └─────────────────┬─────────────────┘
                                                             │
                                           ┌─────────────────┴─────────────────┐
                                     [Valid Progress]                    [Cycle / Worsened]
                                           │                                   │
                                           ▼                                   ▼
                                 [Next Iteration <= 5]               [Rollback to Best Safe]
```

---

## 3. Fixture Schema Specification

The evaluation corpus is maintained in `tests/fixtures/tailor2/render_fill/cases.json`. Each case adheres to the following machine-readable JSON structure:

```json
{
  "case_id": "string (unique stable identifier, e.g. rf_01_clean_one_page_layout)",
  "category": "string (enum: measurement | expansion | compression | optimization_behavior)",
  "target_id": "string (Top-10 target identifier, e.g. openai_4949)",
  "input_candidate": {
    "candidate_id": "string",
    "sections": ["string"],
    "bullet_count": "integer",
    "font_size_pt": "float",
    "margin_in": "float",
    "spacing_tightness": "float (0.0 = normal, 1.0 = maximum)",
    "skills_count": "integer"
  },
  "unused_evidence": [
    {
      "evidence_id": "string",
      "entry_id": "string",
      "summary": "string",
      "value_score": "float (0.0 to 1.0)",
      "is_supported": "boolean",
      "is_prohibited": "boolean",
      "is_redundant": "boolean",
      "estimated_lines": "integer"
    }
  ],
  "render_measurement": {
    "page_count": "integer",
    "vertical_fill_ratio": "float",
    "bottom_margin_in": "float",
    "has_collision": "boolean",
    "collision_type": "string (none | section_collision | tech_date_collision | page_boundary)",
    "has_overflow": "boolean",
    "min_font_pt": "float",
    "min_margin_in": "float",
    "line_wrap_warnings": ["string"],
    "readability_density_score": "float (0.0 to 1.0)",
    "renderer_status": "string (SUCCESS | FAILED_CRASH | TIMEOUT)"
  },
  "protected_facts": [
    "string (exact numerical metrics, canonical titles, technical guarantees)"
  ],
  "allowed_actions": [
    "string (permitted optimizer moves, e.g. swap_shorter_variant, add_unused_bullet)"
  ],
  "forbidden_actions": [
    "string (prohibited actions, e.g. delete_supported_metric, shrink_font_below_minimum)"
  ],
  "expected_layout_state": "string (enum: CLEAN_FIT | MINOR_UNDERFILL | MEANINGFUL_UNDERFILL | SLIGHT_OVERFLOW | SUBSTANTIAL_OVERFLOW | TWO_PAGE_OVERFLOW | BOUNDS_VIOLATION | COLLISION_DETECTED | LINE_WRAP_DEFECT | FONT_SIZE_VIOLATION | MARGIN_VIOLATION | UNREADABLE_COMPRESSION | RENDER_FAILURE)",
  "expected_runtime_outcome": "string (enum: ACCEPTED | ACCEPTED_WITH_WARNING | OPTIMIZATION_EXPANDED | OPTIMIZATION_COMPRESSED | OPTIMIZATION_ROLLED_BACK | NEEDS_HUMAN_REVIEW | FATAL_RENDER_ERROR)",
  "expected_decision_properties": [
    "string (declarative rules governing optimizer decision)"
  ],
  "tolerance_policy": {
    "fill_ratio_tolerance": "float (+/- margin)",
    "min_font_size_pt": "float",
    "min_margin_in": "float",
    "max_compression_tightness": "float"
  },
  "notes": "string (engineering context and target contribution)"
}
```

---

## 4. Evaluation Categories & Case Breakdown (48 Total)

The corpus contains exactly 48 structured test cases:

### 4.1 Measurement (14 Cases: `rf_01` – `rf_14`)
Evaluates the physical and geometric assessment of rendered output:
1. **`rf_01_clean_one_page_layout` (OpenAI 4949):** Fill ratio 0.94, page count 1, zero collisions, zero overflow. State: `CLEAN_FIT`, Outcome: `ACCEPTED`.
2. **`rf_02_minor_harmless_underfill` (RoadRunner 5027):** Fill ratio 0.88, harmless vertical whitespace; accepted with advisory notice rather than fatal rejection. State: `MINOR_UNDERFILL`, Outcome: `ACCEPTED_WITH_WARNING`.
3. **`rf_03_meaningful_underfill` (OpenAI 4949):** Fill ratio 0.74; triggers ledger query to identify high-value unused evidence. State: `MEANINGFUL_UNDERFILL`, Outcome: `OPTIMIZATION_EXPANDED`.
4. **`rf_04_slight_overflow` (DoorDash 4608):** Fill ratio 1.03 (1 line spilling to page 2); solvable via compact bullet variant. State: `SLIGHT_OVERFLOW`, Outcome: `OPTIMIZATION_COMPRESSED`.
5. **`rf_05_substantial_overflow` (Twitch 4182):** Fill ratio 1.15 (5-6 lines spilling); requires multi-pronged variant shortening and spacing. State: `SUBSTANTIAL_OVERFLOW`, Outcome: `OPTIMIZATION_COMPRESSED`.
6. **`rf_06_two_page_output` (TikTok 4164):** Fill ratio 1.45 (half page of overflow); exceeds safe automated compression; routes to human review. State: `TWO_PAGE_OVERFLOW`, Outcome: `NEEDS_HUMAN_REVIEW`.
7. **`rf_07_text_outside_page_bounds` (Zoom 4766):** Text extending past physical printable canvas margins (<0.25in). State: `BOUNDS_VIOLATION`, Outcome: `OPTIMIZATION_COMPRESSED`.
8. **`rf_08_section_collision` (OpenAI 4949):** Over-tightening causes vertical overlap between Experience and Projects headers. State: `COLLISION_DETECTED`, Outcome: `OPTIMIZATION_COMPRESSED`.
9. **`rf_09_project_tech_date_collision` (LexisNexis 4987):** Long project tech line (width 0.78\textwidth) collides horizontally with right-aligned date. State: `COLLISION_DETECTED`, Outcome: `OPTIMIZATION_COMPRESSED`.
10. **`rf_10_suspicious_line_wrapping` (TikTok 4164):** Single-word orphan wrap ("clusters.") on newline wasting full vertical line height. State: `LINE_WRAP_DEFECT`, Outcome: `OPTIMIZATION_COMPRESSED`.
11. **`rf_11_minimum_font_violation` (ID.me 3981):** Rendered font 8.0pt violates policy minimum 9.5pt; rolled back. State: `FONT_SIZE_VIOLATION`, Outcome: `OPTIMIZATION_ROLLED_BACK`.
12. **`rf_12_margin_violation` (RoadRunner 5027):** Margins reduced to 0.25in violate minimum 0.45in policy; rolled back. State: `MARGIN_VIOLATION`, Outcome: `OPTIMIZATION_ROLLED_BACK`.
13. **`rf_13_technically_one_page_unreadable_compression` (Twitch 4182):** Technically 1 page but squished (readability 0.32); density rejected in favor of legibility. State: `UNREADABLE_COMPRESSION`, Outcome: `OPTIMIZATION_ROLLED_BACK`.
14. **`rf_14_renderer_failure_prior_safe_artifact` (OpenAI 4949):** Compiler crashes on experimental tweak; falls back cleanly to prior safe artifact. State: `RENDER_FAILURE`, Outcome: `ACCEPTED_WITH_WARNING`.

### 4.2 Expansion (11 Cases: `rf_15` – `rf_25`)
Evaluates filling vertical whitespace with verified, high-value evidence:
15. **`rf_15_strong_unused_evidence_fits` (OpenAI 4949):** Strong unused item (`rft_b01`, 3-tier ingestion engine) promoted to fill space and improve coverage. State: `MEANINGFUL_UNDERFILL`, Outcome: `OPTIMIZATION_EXPANDED`.
16. **`rf_16_strong_evidence_redundant_rejected` (Twitch 4182):** Strong unused item is redundant with existing bullets (duplicate Postgres); rejected to preserve diversity. State: `MINOR_UNDERFILL`, Outcome: `ACCEPTED_WITH_WARNING`.
17. **`rf_17_low_value_filler_rejected` (DoorDash 4608):** Trivial coursework note (`cm_b5`) rejected as filler; whitespace preferred over fluff. State: `MINOR_UNDERFILL`, Outcome: `ACCEPTED_WITH_WARNING`.
18. **`rf_18_prohibited_evidence_blocked` (TikTok 4164):** Unapproved title substitution strictly blocked from entering expansion pool. State: `MEANINGFUL_UNDERFILL`, Outcome: `ACCEPTED_WITH_WARNING`.
19. **`rf_19_unsupported_evidence_blocked` (ID.me 3981):** Unevidenced Kubernetes cluster project strictly blocked from expansion. State: `MEANINGFUL_UNDERFILL`, Outcome: `ACCEPTED_WITH_WARNING`.
20. **`rf_20_richer_variant_preferred_to_new_bullet` (Zoom 4766):** Expanding existing compact bullet to rich 2-line variant preferred over adding weak bullet. State: `MINOR_UNDERFILL`, Outcome: `OPTIMIZATION_EXPANDED`.
21. **`rf_21_supported_skill_fills_limited_space` (LexisNexis 4987):** Remaining 1-line gap filled safely by adding supported skills (Docker, Git) rather than overflowing bullet. State: `MINOR_UNDERFILL`, Outcome: `OPTIMIZATION_EXPANDED`.
22. **`rf_22_complete_skills_inventory_not_dumped` (OpenAI 4949):** Wholesale dump of all 35+ profile skills blocked; space allocated to engineering evidence instead. State: `MEANINGFUL_UNDERFILL`, Outcome: `OPTIMIZATION_EXPANDED`.
23. **`rf_23_expansion_overflow_rolled_back` (C3.ai 4894):** Adding a 3-line bullet causes page 2 overflow; optimizer rolls back to clean 1-page state. State: `SLIGHT_OVERFLOW`, Outcome: `OPTIMIZATION_ROLLED_BACK`.
24. **`rf_24_two_additions_only_higher_value_fits` (Commure 4839):** Space permits exactly 1 addition; clinical AI (`sepsis_b1`, value 0.95) selected over student project (value 0.55). State: `MEANINGFUL_UNDERFILL`, Outcome: `OPTIMIZATION_EXPANDED`.
25. **`rf_25_blank_space_remains_no_meaningful_evidence` (RoadRunner 5027):** Blank space remains but no meaningful evidence is left; accepted cleanly with warning. State: `MINOR_UNDERFILL`, Outcome: `ACCEPTED_WITH_WARNING`.

### 4.3 Compression (10 Cases: `rf_26` – `rf_35`)
Evaluates compressing overflowing content while preserving facts and readability:
26. **`rf_26_shorter_variant_resolves_slight_overflow` (DoorDash 4608):** Swapping verbose bullet for 1-line variant brings layout to 0.98 fill cleanly. State: `SLIGHT_OVERFLOW`, Outcome: `OPTIMIZATION_COMPRESSED`.
27. **`rf_27_wording_compression_preserves_facts` (TikTok 4164):** Prose tightening preserves exact numbers (`862`, `~70%`) while eliminating newline wrap. State: `SLIGHT_OVERFLOW`, Outcome: `OPTIMIZATION_COMPRESSED`.
28. **`rf_28_approximation_marker_survives_compression` (Twitch 4182):** Tilde approximation marker (`~40%`) preserved without converting to exact 40%. State: `SLIGHT_OVERFLOW`, Outcome: `OPTIMIZATION_COMPRESSED`.
29. **`rf_29_compression_deleting_achievement_rejected` (Commure 4839):** Proposal deleting AUROC 0.88 to save a line is strictly rejected and rolled back. State: `SLIGHT_OVERFLOW`, Outcome: `OPTIMIZATION_ROLLED_BACK`.
30. **`rf_30_spacing_adjustment_within_limits_succeeds` (Zoom 4766):** Micro-overflow (0.5 line) resolved via subtle itemsep adjustment within safe readability limits. State: `SLIGHT_OVERFLOW`, Outcome: `OPTIMIZATION_COMPRESSED`.
31. **`rf_31_spacing_adjustment_below_minimum_rejected` (ID.me 3981):** Spacing adjustment below readability threshold (tightness > 0.85) is rejected. State: `UNREADABLE_COMPRESSION`, Outcome: `OPTIMIZATION_ROLLED_BACK`.
32. **`rf_32_redundant_content_removed_last_resort` (LexisNexis 4987):** All spacing/shortening exhausted; removing lowest-value redundant bullet succeeds as last resort. State: `SUBSTANTIAL_OVERFLOW`, Outcome: `OPTIMIZATION_COMPRESSED`.
33. **`rf_33_hardcoded_bullet_deletion_prohibited` (OpenAI 4949):** Naive bullet truncation (e.g. `bullets[:10]`) is strictly prohibited; routes to human review. State: `SUBSTANTIAL_OVERFLOW`, Outcome: `NEEDS_HUMAN_REVIEW`.
34. **`rf_34_compression_worsens_layout_rolled_back` (C3.ai 4894):** Compression attempt produced a date collision; rolled back to prior candidate. State: `COLLISION_DETECTED`, Outcome: `OPTIMIZATION_ROLLED_BACK`.
35. **`rf_35_all_compression_fails_usable_preview_remains` (OpenAI 4949):** All compression options exhausted; system generates clean preview PDF and routes to human review. State: `SUBSTANTIAL_OVERFLOW`, Outcome: `NEEDS_HUMAN_REVIEW`.

### 4.4 Optimization Behavior (13 Cases: `rf_36` – `rf_48`)
Evaluates convergence, budgets, precedence rules, and traceability:
36. **`rf_36_best_safe_candidate_survives_worse_iteration` (OpenAI 4949):** Iteration 1 safe candidate restored when later iteration degrades. State: `SLIGHT_OVERFLOW`, Outcome: `OPTIMIZATION_ROLLED_BACK`.
37. **`rf_37_iteration_budget_terminates` (RoadRunner 5027):** Optimizer terminates cleanly when iteration budget (5) is reached. State: `MINOR_UNDERFILL`, Outcome: `ACCEPTED_WITH_WARNING`.
38. **`rf_38_provider_call_budget_terminates` (TikTok 4164):** LLM regeneration calls strictly bounded to budget (4); falls back to deterministic rules. State: `SLIGHT_OVERFLOW`, Outcome: `ACCEPTED_WITH_WARNING`.
39. **`rf_39_resumed_optimization_skips_completed` (Zoom 4766):** Resumption recognizes prior checkpoint artifacts and avoids re-executing steps. State: `CLEAN_FIT`, Outcome: `ACCEPTED`.
40. **`rf_40_candidate_fingerprint_prevents_cycles` (Twitch 4182):** Fingerprint hash detects cyclic oscillation between states and breaks loop immediately. State: `SLIGHT_OVERFLOW`, Outcome: `OPTIMIZATION_ROLLED_BACK`.
41. **`rf_41_fill_percentage_alone_does_not_determine_acceptance` (OpenAI 4949):** 98% fill ratio rejected because section collision exists; fill ratio is not the sole metric. State: `COLLISION_DETECTED`, Outcome: `OPTIMIZATION_COMPRESSED`.
42. **`rf_42_collision_outranks_fill_ratio` (LexisNexis 4987):** Fixing heading collision strictly outranks keeping fill ratio at 0.95. State: `COLLISION_DETECTED`, Outcome: `OPTIMIZATION_COMPRESSED`.
43. **`rf_43_readability_outranks_maximum_density` (C3.ai 4894):** Candidate with 0.92 readability and 0.91 fill preferred over 0.45 readability and 0.99 fill. State: `CLEAN_FIT`, Outcome: `ACCEPTED`.
44. **`rf_44_factual_integrity_outranks_layout_score` (TikTok 4164):** Candidate altering 862 to fit 1 page rejected; factual integrity strictly outranks layout fit. State: `SLIGHT_OVERFLOW`, Outcome: `OPTIMIZATION_ROLLED_BACK`.
45. **`rf_45_unresolved_usable_layout_maps_to_human_review` (Commure 4839):** Marginal 1-line overflow with protected clinical metrics routes to human review with preview PDF. State: `SLIGHT_OVERFLOW`, Outcome: `NEEDS_HUMAN_REVIEW`.
46. **`rf_46_minor_underfill_maps_to_warning_or_acceptance` (DoorDash 4608):** 0.89 fill ratio is clean and legible; maps to `ACCEPTED_WITH_WARNING`, never fatal. State: `MINOR_UNDERFILL`, Outcome: `ACCEPTED_WITH_WARNING`.
47. **`rf_47_no_safe_render_maps_to_fatal_only_when_unrecoverable` (Zoom 4766):** Unrecoverable renderer failure with zero prior safe artifacts correctly maps to `FATAL_RENDER_ERROR`. State: `RENDER_FAILURE`, Outcome: `FATAL_RENDER_ERROR`.
48. **`rf_48_all_intermediate_artifacts_traceable` (OpenAI 4949):** All intermediate steps, renders, measurements, and decisions are archived and traceable. State: `CLEAN_FIT`, Outcome: `ACCEPTED`.

---

## 5. Cross-Target Coverage Across Top-10 Corpus

Every target from `shortlist/tailoring_targets/targets.json` contributes specific layout characteristics:

| Target ID | Company | Exact Role | Cases | Layout & Typographic Stresses Contributed |
|:---|:---|:---|:---:|:---|
| `openai_4949` | OpenAI | Software Engineer - Applied Emerging Talent | 11 | Deepest acceptance baseline; vertical whitespace expansion; section collision recovery; whole-skills dump prevention; best-safe candidate persistence; full artifact audit ledger. |
| `tiktok_4164` | TikTok | Backend Software Engineer Graduate (Global E-commerce) | 6 | High-throughput distributed systems; exact metric (`862`, `~70%`) preservation during compression; orphan word wrapping (`clusters.`); two-page overflow handling; provider call budgets. |
| `twitch_4182` | Twitch | Software Engineer I, Payments | 5 | Dense banking concurrency; substantial overflow compression; unreadable squishing rejection; approximation marker preservation (`~40%`); candidate oscillation cycle detection. |
| `zoom_4766` | Zoom | Software Development Engineer | 5 | Project-heavy networking (PeerChat); printable canvas bounds enforcement; rich variant expansion over new bullets; compiler failure fallback; unrecoverable crash mapping. |
| `doordash_4608` | DoorDash | Software Engineer 1 - Entry-Level | 4 | Low-latency dispatch; slight overflow resolution via 1-line variant swap; coursework filler rejection; clean underfill acceptance. |
| `roadrunner_5027` | RoadRunner | Forward Deployed Engineer New Grad | 4 | Commercial experience prominence; harmless whitespace handling; margin violation rollback; iteration budget termination. |
| `lexisnexis_4987` | LexisNexis | Software Engineer 1 - Aspire Graduate Program | 4 | Enterprise data retention; horizontal heading/date collision resolution; supported skill expansion; redundant bullet removal as last resort. |
| `c3ai_4894` | C3.ai | Platform Full-Stack Engineer New Grad | 3 | ML platform; expansion overflow rollback; compression collision detection; readability outranking maximum density. |
| `commure_4839` | Commure | Software Engineer - Early Career | 3 | Healthcare compliance; clinical metric deletion prevention (AUROC 0.88); higher-value evidence expansion; preview PDF generation for human review. |
| `idme_3981` | ID.me | Software Development Engineer New Grad | 3 | Identity security; unevidenced skill expansion blocking; minimum font size policy enforcement (9.5pt); extreme spacing rejection. |

---

## 6. Recorded Iteration Scenarios (12 Scenarios)

The twelve recorded scenario traces in `tests/fixtures/tailor2/render_fill/recorded_scenarios/` demonstrate end-to-end optimizer behavior:

1. **`01_underfill_add_strong_bullet_clean_fit.json`:** Underfill (0.76) queries unused ledger, selects `rft_b01` (value 0.95), re-renders at 0.94 fill -> `CLEAN_FIT`, `ACCEPTED`.
2. **`02_underfill_attempted_filler_rejected.json`:** Underfill (0.82) evaluates `cm_b5` (value 0.20), rejects filler to preserve signal-to-noise ratio -> `ACCEPTED_WITH_WARNING`.
3. **`03_slight_overflow_shorter_variant_clean_fit.json`:** Overflow (1.02, 1 line on page 2) swaps bullet `b02` to 1-line variant (holding `862`, `~70%`) -> 0.98 fill -> `CLEAN_FIT`, `ACCEPTED`.
4. **`04_overflow_safe_compression_clean_fit.json`:** Overflow (1.06, 2 lines) combines 1-line variant swap with subtle itemsep tightening (0.40) -> 0.97 fill -> `CLEAN_FIT`, `ACCEPTED`.
5. **`05_overflow_bad_compression_rollback.json`:** Aggressive font reduction to 8.0pt causes `FONT_SIZE_VIOLATION` (readability 0.35); optimizer rolls back to safe candidate state.
6. **`06_collision_despite_acceptable_fill_ratio.json`:** Fill ratio 0.94 acceptable, but tech-line collides with date; compresses tech line to clear collision -> `CLEAN_FIT`, `ACCEPTED`.
7. **`07_render_failure_prior_safe_fallback.json`:** Compiler crashes on experimental macro tweak; optimizer catches crash and restores Iteration 1 safe PDF artifact -> `ACCEPTED_WITH_WARNING`.
8. **`08_optimizer_cycle_detected.json`:** Fingerprint hash detects candidate state oscillation between 1.02 and 0.88; terminates loop and returns best safe 1-page candidate.
9. **`09_iteration_budget_exhausted.json`:** Optimizer hits max iteration budget (5) on stubborn layout; terminates cleanly with best safe candidate -> `ACCEPTED_WITH_WARNING`.
10. **`10_human_review_outcome_with_usable_pdf.json`:** Marginal 1-line overflow with protected metrics cannot be compressed safely; exports usable preview PDF and routes to `NEEDS_HUMAN_REVIEW`.
11. **`11_no_meaningful_expansion_evidence.json`:** Minor underfill (0.84), but ledger is empty; terminates expansion cleanly without fabricating filler -> `ACCEPTED_WITH_WARNING`.
12. **`12_metric_altering_compression_candidate_rejected.json`:** Automated compression proposing to drop `862` or strip tilde from `~70%` is intercepted and rejected by factual integrity validator.

---

## 7. Portability & Non-Brittleness Decisions

1. **No Exact Pixel Assertions:** Bounding box and coordinate assertions are normalized as relative typographic units (e.g. `\textwidth` ratios, vertical fill percentage, point-based font sizes) to avoid platform-dependent font rasterization drift.
2. **Justified Tolerances:** Measurement policies declare portable tolerances (`fill_ratio_tolerance: 0.03`, `min_font_pt: 9.5`, `min_margin_in: 0.45`).
3. **No Mandatory 97% Fill Threshold:** Minor underfill (0.85 – 0.90) is recognized as clean, legible whitespace and accepted with advisory warnings rather than fatal errors.
4. **Readability Over Maximum Density:** A 0.91 fill layout with clean line spacing strictly outranks a 0.99 fill layout with squished text.
5. **Zero Factual Corruption:** Prose compression must never round integers (`862`), delete tildes (`~70%`), or remove verified metrics (`AUROC 0.88`).

---

## 8. Test Suite & Acceptance Scaffolding

Located at `tests/tailor2/test_render_fill_fixtures.py`:
- Fixture schema conformance and ID uniqueness.
- Layout state and runtime outcome enum validation.
- Portable tolerance validation and geometry internal consistency.
- Evidence resolution (canonical catalog vs `synth_*` tags).
- Metric and approximation marker preservation.
- Negative rejection of filler, prohibited, and unsupported claims.
- Rollback and prior-best candidate persistence.
- Zero PII (emails, phone numbers, street addresses) and zero provider secrets.
- 5 strict xfail integration tests scaffolding the future production optimizer.

Execution command:
```bash
pytest -q tests/tailor2/test_render_fill_fixtures.py
```
