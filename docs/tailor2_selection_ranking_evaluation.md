# Tailor2 Semantic Selection and Multi-Candidate Ranking Evaluation Specification

## 1. Overview & Objective

This document defines the deterministic evaluation corpus, fixture schema, and test harness for the next phase of the Tailor2 résumé tailoring pipeline: **semantic selection and multi-candidate ranking**.

Tailor2 shifts from brittle, keyword-stuffed drafting to a dual-stage architecture:
1. **Semantic Requirement Interpretation & Evidence Selection:** Translates job description (JD) requirements into atomic requirements with explicit boolean semantics (preserving alternative OR groups, distinguishing must-haves from preferred bonuses), maps them to canonically verified profile evidence, and selects optimal evidence subsets without arbitrary ID locks.
2. **Multi-Candidate Generation & Two-Tier Ranking:** Generates multiple factually invariant bullet candidates per evidence slot (varying rhetoric and syntax, holding metrics and guarantees constant), ranks candidates locally (favoring outcomes over feature catalogues), and ranks the entire document globally (penalizing repetitive sentence syntax, buzzword density, and requirement crowding).
3. **Curated Skills & Unused-Evidence Ledger:** Curates target-relevant technical skills while preventing full inventory dumps or unevidenced ATS injections; catalogs strong omitted evidence into an auditable ledger for dynamic vertical space page-filling.
4. **Resilient Error Severity Routing:** Prevents quality defects (e.g. whitespace, stylistic repetitions) from becoming fatal pipeline aborts, reserving `FATAL_INTEGRITY` strictly for factual fabrication, title tampering, or metric corruption.

No live LLM calls are used in evaluation. All tests and fixtures are machine-readable, deterministic, and fully reproducible.

---

## 2. Fixture Schema Specification

The evaluation corpus is stored in machine-readable JSON at `tests/fixtures/tailor2/selection_ranking/cases.json`. Each case adheres to the following formal schema:

```json
{
  "case_id": "string (unique stable identifier, e.g. sel_01_or_group_degree_or_exp)",
  "category": "string (enum: requirement_interpretation | semantic_matching | evidence_selection | skills_selection | multi_candidate_generation | resume_ranking | unused_evidence_page_fill)",
  "target_id": "string (target identifier corresponding to Top-10 targets, e.g. openai_4949)",
  "requirement": {
    "id": "string (unique requirement ID, e.g. req_edu_or_exp)",
    "raw_quote": "string (exact textual snippet extracted from target JD)",
    "interpreted_intent": "string (semantic interpretation of what the requirement entails)",
    "importance": "string (enum: must_have | preferred | nice_to_have)",
    "is_alternative_or_group": "boolean (true if qualifications represent alternative options)",
    "alternative_options": ["string (list of alternative qualification branches, if any)"]
  },
  "candidate_evidence": [
    {
      "evidence_id": "string (canonical evidence ID resolving to canonical catalog)",
      "entry_id": "string (canonical profile entry ID, e.g. amdocs_software_developer)",
      "summary": "string (concise summary of evidenced capability)"
    }
  ],
  "protected_facts": [
    "string (exact metrics, canonical titles, or technical guarantees that cannot drift)"
  ],
  "expected_matches": [
    "string (canonical evidence IDs or skill terms expected to match)"
  ],
  "expected_non_matches": [
    "string (evidence IDs or skills that must NOT match, e.g. unrelated technologies)"
  ],
  "expected_selection_properties": [
    "string (behavioral criteria expected during selection)"
  ],
  "expected_ranking_properties": [
    "string (criteria expected during local or whole-résumé ranking)"
  ],
  "expected_runtime_severity": "string (enum: CLEAN_PASS | ADVISORY_GAP | AUTO_CORRECTABLE | REPAIRABLE_QUALITY | NEEDS_HUMAN_REVIEW | FATAL_INTEGRITY)",
  "forbidden_inferences": [
    "string (inferences the pipeline or evaluator is strictly prohibited from making)"
  ],
  "acceptable_variation": [
    "string (permissible variations in rhetoric, verb choice, or structure)"
  ],
  "notes": "string (engineering context and target contribution)",
  "candidate_variants": [
    {
      "variant_id": "string",
      "text": "string",
      "evidence_ids": ["string"],
      "is_factually_valid": "boolean",
      "ranking_score": "float (0.0 to 1.0)"
    }
  ],
  "omission_reason": "string (enum: space_constraint | lower_target_relevance | redundant_coverage | single_employer_cap)",
  "page_budget_priority": "integer (1 = highest priority for blank space expansion)"
}
```

### Field Definitions
* `case_id`: Stable identifier naming the case and its core evaluation property.
* `category`: One of the 7 required evaluation domains.
* `target_id`: Formatted as `<company_prefix>_<job_id>`, resolving to `shortlist/tailoring_targets/targets.json`.
* `requirement`: Structured representation of the job description demand, including raw quote, semantic intent, importance tier, and boolean OR branching.
* `candidate_evidence`: List of evidence items drawn from the candidate profile. All `evidence_id` fields resolve to `tests/fixtures/tailor2/quality_regressions/canonical_evidence_catalog.json`.
* `protected_facts`: Immutable factual elements (e.g. `862 dead-letter topics`, `~70%`, `~40%`, `PostgreSQL atomic reservations`, `Software Developer` title) that must be preserved verbatim across candidate variants.
* `expected_matches`: Canonical evidence IDs or skills that semantically satisfy the requirement.
* `expected_non_matches`: Technologies or evidence items that must not match (guarding against false lexical coincidence).
* `expected_selection_properties`: Declarative behavioral properties governing evidence choice (e.g. outcome over mechanism, employment prominence).
* `expected_ranking_properties`: Declarative rules governing ranking (e.g. redundancy penalty, diverse requirement coverage).
* `expected_runtime_severity`: The expected system outcome classification under Tailor2 error taxonomy.
* `forbidden_inferences`: Unwarranted assumptions or exaggerations that the model/evaluator is barred from making.
* `acceptable_variation`: Explicitly documented areas of permissible stylistic and syntactic freedom.
* `notes`: Contextual explanation of the case design and role significance.
* `candidate_variants`: (Optional) Structured multi-candidate bullet variants testing local ranking and rhetorical variation.
* `omission_reason`: (Optional, for unused evidence) Categorical rationale for omitting verified evidence.
* `page_budget_priority`: (Optional, for page fill) Numeric ranking priority for vertical space expansion.

---

## 3. Evaluation Categories & Case Catalog

The corpus contains exactly **48 test cases** distributed across 7 categories:

### 3.1 Requirement Interpretation (5 cases: `sel_01` – `sel_05`)
Evaluates whether raw JD requirements are accurately parsed without introducing false constraints:
1. **`sel_01_or_group_degree_or_exp` (OpenAI 4949):** Alternative degree or experience requirement remains one OR group. A candidate satisfying the experience branch or possessing an advanced degree satisfies the requirement without requiring both.
2. **`sel_02_req_vs_pref_qualifications` (Twitch 4182):** Required versus preferred qualifications remain distinct. Preferred items (PCI compliance) boost score when present, but missing preferred items never act as eligibility blockers.
3. **`sel_03_responsibilities_not_mandatory_gates` (TikTok 4164):** Day-to-day job responsibilities describe role scope; they are not converted into mandatory prerequisite entry gates.
4. **`sel_04_ambiguous_jd_wording` (RoadRunner 5027):** Ambiguous qualitative traits ("deep curiosity, high ownership") are represented without inventing arbitrary keywords (e.g. "curiosity certification").
5. **`sel_05_missing_product_evidence_disclosed_gap` (OpenAI 4949):** Missing consumer frontend or product evidence is surfaced as a disclosed advisory gap (`ADVISORY_GAP`), not a fatal pipeline crash.

### 3.2 Semantic Matching (7 cases: `sel_06` – `sel_12`)
Evaluates semantic understanding of engineering concepts and technologies:
6. **`sel_06_postgres_postgresql_equivalence` (DoorDash 4608):** `Postgres` and `PostgreSQL` match bi-directionally as canonical synonyms.
7. **`sel_07_react_canonical_support_boundary` (C3.ai 4894):** The current profile has no canonical React or Vue support; the frontend gap remains disclosed and unsupported framework aliases are not injected.
8. **`sel_08_ai_ml_interest_vs_research` (OpenAI 4949):** Applied ML and LLM prompt engineering evidence is matched to AI interest requirements without exaggerating the candidate into a foundational AI research scientist.
9. **`sel_09_backend_systems_adjacent_to_product` (OpenAI 4949):** Backend systems evidence is recognized as adjacent and transferable to applied-product requirements without masquerading as direct UI/UX design.
10. **`sel_10_unrelated_technologies_rejected` (Zoom 4766):** Unrelated technologies (Kafka distributed queues vs WebRTC real-time media streaming) do not match merely because both are backend systems.
11. **`sel_11_transferable_vs_direct_evidence` (Twitch 4182):** Transferable banking transaction ledgers and double-entry reservations are distinguished from direct merchant payment gateways while remaining highly ranked.
12. **`sel_12_semantic_equivalence_metric_preservation` (TikTok 4164):** Semantic matching never mutates, rounds, or inflates protected metrics (`862`, `~70%`).

### 3.3 Evidence and Project Selection (8 cases: `sel_13` – `sel_20`)
Evaluates evidence selection heuristics under space constraints:
13. **`sel_13_strong_role_outranks_weak_keyword_project` (LexisNexis 4987):** Verified production employment experience outranks a weaker keyword-stuffed classroom project.
14. **`sel_14_mechanism_catalogue_loses_to_outcome` (DoorDash 4608):** A configuration catalogue (thread pools, tuning flags) loses in selection to demonstrated architectural outcomes (`~40% lock contention reduction`).
15. **`sel_15_employment_not_buried_by_projects` (RoadRunner 5027):** Commercial employment evidence receives primary visual hierarchy and is not buried beneath projects.
16. **`sel_16_single_employer_space_capped` (Commure 4839):** A single employer (Amdocs) does not consume excessive space when diverse strong evidence exists across other roles and healthcare-relevant projects.
17. **`sel_17_adaptable_selection_without_mandatory_ids` (C3.ai 4894):** Selection adapts across multiple valid evidence subsets without requiring a single hardcoded combination of IDs.
18. **`sel_18_unsupported_capabilities_remain_gaps` (Twitch 4182):** Unsupported capabilities (mobile iOS/Android payment SDKs) remain honest disclosed gaps rather than hallucinated claims.
19. **`sel_19_agentic_ai_without_repetitive_buzzwords` (OpenAI 4949):** Agentic AI workflow evidence is selected on technical merit without forcing repeated, repetitive AI buzzwords in every bullet.
20. **`sel_20_value_per_line_without_rigid_cutoff` (Zoom 4766):** High information density per line is prioritized without imposing a rigid, brittle character count cutoff.

### 3.4 Skills Selection (7 cases: `sel_21` – `sel_27`)
Evaluates curation of the Technical Skills section:
21. **`sel_21_supported_relevant_skill_eligible` (TikTok 4164):** Supported and target-relevant skills (Python, Java, Kafka) are eligible for display.
22. **`sel_22_supported_skill_not_mandatory_display` (Twitch 4182):** A supported skill (C++) need not appear merely because it exists in the master profile; display is an editorial choice.
23. **`sel_23_supported_skill_without_bullet` (DoorDash 4608):** Supported developer tools (Git, Linux, Docker) may appear in the Skills section without requiring a dedicated experience bullet.
24. **`sel_24_unsupported_skill_blocked_for_ats` (ID.me 3981):** Unsupported skills (Ruby on Rails, Kubernetes) cannot be injected into the Skills section for ATS keyword matching; injection is `FATAL_INTEGRITY`.
25. **`sel_25_auxiliary_tooling_not_dominating` (RoadRunner 5027):** Low-value auxiliary utilities (Jira, Postman, Slack) must not crowd out core engineering competencies.
26. **`sel_26_semantic_aliases_preserve_concept` (LexisNexis 4987):** Semantic aliases (`PostgreSQL` / `Postgres`) preserve canonical concepts and prevent duplicate entries.
27. **`sel_27_inventory_dump_prevented` (OpenAI 4949):** The complete 35+ profile inventory is not dumped into the résumé; skills are curated for target relevance.

### 3.5 Multi-Candidate Bullet Generation (8 cases: `sel_28` – `sel_35`)
Evaluates candidate bullet generation and local variant ranking:
28. **`sel_28_candidate_variants_preserve_evidence_ids` (TikTok 4164):** All generated candidate variants for a bullet slot preserve the same canonical evidence ID (`am_b01_dlq_consolidation`).
29. **`sel_29_candidate_variants_preserve_exact_metrics` (TikTok 4164):** Exact integer metrics (`862`) must not be rounded or altered across candidate variants.
30. **`sel_30_approximation_markers_preserved` (TikTok 4164):** Approximation markers (`~70%`, `~40%`) must not be stripped to create exact percentages.
31. **`sel_31_candidates_vary_rhetoric_not_facts` (Twitch 4182):** Candidates vary syntactic structures (STAR vs XYZ) and active verbs while holding facts invariant.
32. **`sel_32_feature_catalogue_loses_to_outcome` (OpenAI 4949):** Feature-catalogue wording loses in ranking to a clear outcome-oriented candidate.
33. **`sel_33_undefined_metric_loses_to_interpretable` (ID.me 3981):** Undefined or ungrounded metrics ("100x speedup") lose to clear, interpretable, evidenced formulations.
34. **`sel_34_repair_cannot_delete_supported_achievement` (Commure 4839):** A conciseness repair cannot improve flow by deleting a supported quantitative achievement (AUROC 0.88).
35. **`sel_35_fabricated_polished_candidate_ineligible` (Zoom 4766):** A fabricated bullet is strictly ineligible regardless of prose polish; triggers `FATAL_INTEGRITY`.

### 3.6 Résumé-Level Ranking (7 cases: `sel_36` – `sel_42`)
Evaluates whole-document composition and global narrative quality:
36. **`sel_36_repeated_sentence_structures_penalized` (RoadRunner 5027):** Repeated sentence structures (3+ consecutive bullets starting with "Built [X] using [Y]") incur a redundancy penalty.
37. **`sel_37_repeated_ai_abstractions_visible` (OpenAI 4949):** Overuse of vague AI buzzwords across headers and bullets is detected and penalized.
38. **`sel_38_duplicate_requirement_crowding_penalized` (Twitch 4182):** Multiple bullets evidencing the same requirement cannot crowd out coverage of other must-have requirements.
39. **`sel_39_whole_resume_positioning_matters` (OpenAI 4949):** Whole-résumé candidate narrative coherence matters beyond isolated local bullet scores.
40. **`sel_40_misleading_applied_product_positioning_flagged` (OpenAI 4949):** Factual but misleading applied-product positioning (framing database archiving as UX design) is flagged for human review (`NEEDS_HUMAN_REVIEW`).
41. **`sel_41_buried_strong_evidence_triggers_reordering` (C3.ai 4894):** Strong evidence buried below weak evidence triggers reordering.
42. **`sel_42_uncertain_evaluator_fallback_usable` (LexisNexis 4987):** When an evaluator comparison is within noise threshold, deterministic fallback preserves usable output without crashing.

### 3.7 Unused Evidence and Future Page Fill (6 cases: `sel_43` – `sel_48`)
Evaluates the unused evidence ledger and vertical space management:
43. **`sel_43_strong_omitted_evidence_in_ledger` (OpenAI 4949):** Strong omitted evidence is retained in a structured unused-evidence ledger.
44. **`sel_44_unused_items_record_omission_reasons` (OpenAI 4949):** Each unused item explicitly records why it was omitted (`space_constraint`, `lower_target_relevance`, etc.).
45. **`sel_45_blank_space_expansion_ranks_unused_evidence` (DoorDash 4608):** Blank-space expansion queries the ledger to select the highest-value unused evidence to fill vertical whitespace.
46. **`sel_46_ledger_excludes_prohibited_unsupported` (TikTok 4164):** The unused ledger never contains fabricated, prohibited, or unevidenced claims as reserve options.
47. **`sel_47_space_omission_distinguished_from_irrelevance` (Twitch 4182):** Omission due to 1-page space constraints is clearly distinguished from omission due to irrelevance.
48. **`sel_48_valid_resume_unused_space_not_fatal` (RoadRunner 5027):** A valid résumé with unused vertical whitespace is not fatally rejected; whitespace is an optimization target, not an error.

---

## 4. Cross-Target Coverage Across Top-10 Corpus

The corpus is not restricted to a single role. It draws representative cases across all 10 target opportunities in `shortlist/tailoring_targets/targets.json`:

| Rank | Target Identifier | Company | Role Title | Case Count | Specific Semantic & Selection Behaviors Contributed |
|:---:|:---|:---|:---|:---:|:---|
| 7 | `openai_4949` | OpenAI | Software Engineer - Applied Emerging Talent | 12 | Deepest acceptance baseline; OR-group education parsing; applied ML vs research expertise; backend systems adjacency to product; AI buzzword audit; whole-résumé positioning; unused evidence ledger. |
| 10 | `twitch_4182` | Twitch | Software Engineer I, Payments | 7 | Basic vs preferred qualification distinction; financial ledger transferability; supported skill display curation; rhetoric variation in concurrency bullets; requirement crowding penalty; space omission distinction. |
| 4 | `tiktok_4164` | TikTok | Backend Software Engineer Graduate (Global E-commerce) | 7 | Job responsibilities vs entry gates; exact metric (`862`) and approximation symbol (`~70%`) preservation; canonical evidence ID binding across candidate variants; unevidenced claim ledger exclusion. |
| 5 | `roadrunner_5027` | RoadRunner | Forward Deployed Engineer New Grad | 5 | Qualitative traits without artificial keywords; commercial employment prominence over projects; auxiliary tooling demotion; repeated syntax penalty; whitespace not fatal. |
| 2 | `doordash_4608` | DoorDash | Software Engineer 1 - Entry-Level | 4 | PostgreSQL/Postgres bi-directional equivalence; outcome over configuration catalogue; supported tools in Skills without bullets; blank-space vertical expansion ranking. |
| 8 | `c3ai_4894` | C3.ai | Platform Full-Stack Engineer New Grad | 3 | React canonical support boundary and Vue exclusion; adaptable selection without mandatory ID locks; reordering buried high-impact evidence. |
| 1 | `zoom_4766` | Zoom | Software Development Engineer | 3 | Rejecting unrelated technologies (Kafka vs WebRTC); high value per line without rigid character cutoffs; disqualifying fabricated polished candidates. |
| 6 | `lexisnexis_4987` | LexisNexis | Software Engineer 1 - Aspire Graduate Program | 3 | Commercial role outranking student project; semantic alias normalization without duplicates; uncertain evaluator fallback. |
| 9 | `commure_4839` | Commure | Software Engineer - Early Career | 2 | Single employer space capping to balance healthcare domain projects; prohibiting deletion of supported metrics during conciseness repair. |
| 3 | `idme_3981` | ID.me | Software Development Engineer New Grad | 2 | Strictly blocking unsupported skills (Kubernetes, Ruby on Rails) from ATS injection; penalizing unevidenced vague metrics (100x). |

---

## 5. Recorded-Response Scenarios

Ten recorded structured response files are maintained in `tests/fixtures/tailor2/selection_ranking/recorded_responses/`:

1. **`01_requirement_interpretation.json`:** Structured output parsing raw JD text into atomic requirements, tagging importance, identifying alternative OR groups, and recording disclosed gaps.
2. **`02_semantic_evidence_matching.json`:** Grounded matching of profile evidence to requirements, demonstrating synonym normalization, applied AI bounding, and explicit rejection of disjoint technologies.
3. **`03_candidate_generation.json`:** Multi-candidate generator output yielding 3 canonical phrasing tiers for `int_b2`, preserving identical evidence IDs and the profile-backed concurrency guarantee.
4. **`04_local_ranking.json`:** Local bullet evaluator scoring, demonstrating how outcome-oriented architectural statements (0.96) outrank component catalogues (0.58).
5. **`05_resume_level_ranking.json`:** Global résumé evaluator assessing narrative coherence, flagging repeated sentence syntax, and evaluating requirement coverage.
6. **`06_malformed_recoverable_output.json`:** Provider output wrapped in markdown fences with leading text and trailing commas; demonstrates robust parser recovery without unhandled exceptions.
7. **`07_factually_invalid_high_scoring_candidate.json`:** Stylistically polished candidate bullet (readability 0.98) containing fabricated scale metrics (10M concurrent connections); demonstrates factual integrity strictly overriding style scores.
8. **`08_omitted_candidate_ranking.json`:** Provider ranking response that omitted candidate `c2_star`; demonstrates detection and deterministic fallback scoring without pipeline abort.
9. **`09_fewer_candidates_than_requested.json`:** Provider generator returning 2 variants instead of 3; demonstrates graceful degradation with an advisory notice rather than crashing.
10. **`10_uncertain_comparison_fallback.json`:** Ranker comparison where candidate score delta is within statistical noise (0.002); demonstrates deterministic fallback to canonical profile order.

---

## 6. Non-Brittleness Rules

To prevent test brittleness and premature coupling to unsettled implementation details, the following rules are enforced:

1. **No Single Golden Prose:** Tests never assert that generated bullets match one exact string. Tests verify semantic invariants, preserved evidence IDs, exact numeric tokens, and structural properties.
2. **No Rigid Bullet Counts:** The harness does not require exactly N bullets per section or exactly M projects.
3. **No Mandatory Evidence ID Locks:** Target selection test cases assert behavioral properties (e.g. balance across employers, relevant domain inclusion) rather than mandating an inflexible combination of IDs.
4. **No Universal Keyword Bans:** Rules penalize repeated buzzwords (e.g. 5+ mentions of AI) and unevidenced technologies, but do not universally ban standard technical words.
5. **No Fatal Penalties for Aesthetic Imperfections:** Stylistic repetition, layout whitespace, and advisory qualification gaps route to `REPAIRABLE_QUALITY`, `ADVISORY_GAP`, or `NEEDS_HUMAN_REVIEW`. `FATAL_INTEGRITY` is reserved strictly for factual falsehoods.

---

## 7. Discovered Evidence Ambiguities

During construction and verification of this evaluation corpus, several domain ambiguities were identified and documented:

1. **Frontend framework gap:** The current candidate master profile does not list `React`, `React.js`, Vue, or another frontend framework. The C3.ai case therefore records the API/storage evidence as a non-match and keeps the frontend gap explicit rather than importing the earlier corpus assumption.
2. **Postgres vs PostgreSQL:** JDs regularly alternate between `Postgres` and `PostgreSQL`. While the profile lists `PostgreSQL`, the pipeline must normalize both as identical relational database concepts without penalizing discrepancies.
3. **Banking Ledger vs Certified Payment Gateway:** Candidate evidence `int_b2` details atomic reservations and double-entry ledgers at MalyTech. This is highly relevant, transferable financial systems engineering, but should not be inflated to claim direct compliance with PCI DSS or direct Visa/Mastercard payment gateway integration.
4. **Applied ML vs Foundational Research:** Projects such as Sepsis Early Warning (`sepsis_b1`) and Fake Review Detection (`frd_b1`) demonstrate applied ML classification and feature engineering. They satisfy "interest in AI/ML", but should not be mischaracterized as foundational AI research or LLM pretraining.
5. **Amdocs Title Fidelity:** Amdocs historical employment is legally verified as `Software Developer`. Even when target JDs solicit `Software Engineer` (e.g. OpenAI), the historical title must remain `Software Developer` to prevent résumé fraud, with auto-correction to canonical rather than pipeline termination.

---

## 8. Test Harness & Execution

The test suite is located at `tests/tailor2/test_selection_ranking_fixtures.py` and validates:
* Strict schema conformance for all 48 cases.
* Complete resolution of all referenced evidence IDs and target IDs.
* SHA-256 integrity and immutability of all 10 target JDs.
* Zero PII (emails, phone numbers, addresses) across all fixtures.
* Numeric token, approximation marker, and factual guarantee preservation.
* Semantic equivalence symmetry and negative match rejection.
* Proper error taxonomy mapping across quality vs integrity defects.
* All 10 recorded response scenarios exist, parse cleanly, and contain no credentials.
* Acceptance tests for pending selection/ranking engine features (marked `strict=True` xfail).

Execution command:
```bash
pytest -q tests/tailor2/test_selection_ranking_fixtures.py
```

## 9. Integration Reconciliation

The production branch was integrated at the exact committed selection implementation, then the independent corpus was exercised through deterministic compatibility adapters. Four strict acceptance xfails now pass: semantic OR-group parsing, profile-backed skill alias selection, bounded canonical candidate generation, and whole-résumé redundancy detection. The unused-evidence ledger is covered normally; measured rendered blank-space expansion remains one strict xfail because static selection cannot prove page geometry.

The recorded `int_b2` examples previously claimed an unsupported `~40%` lock-contention metric. They now use the canonical profile fact that eight concurrent requests produced exactly one downstream provider call. No target company or target ID was removed.
