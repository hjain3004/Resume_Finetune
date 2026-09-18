# Tailor2 Offline Evaluation Plans, Baseline Registry & Release Gates

## 1. Executive Summary

This document specifies the offline evaluation architecture, plan assets, baseline registry, human review protocols, and proposed release gates for the Tailor2 resume tailoring engine.

In accordance with pipeline invariants:
- **Plans are credential-free and deterministic:** Evaluation plans record pinned SHA-256 checksums of the profile and target job descriptions (JDs) to ensure byte-for-byte input reproducibility before any run or comparison is trusted.
- **Evaluation assets are decoupled from model execution:** Plans, baseline registries, templates, and human review rubrics are checked into source control without requiring active network calls, API keys, or live model execution.
- **Strict safety gating:** Live provider execution is isolated behind an explicit `--live` CLI flag, an authorizing runtime argument, and required environment variables (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, etc.). All tests and automated workflows run in `--dry-run` or `--recorded` replay modes.

---

## 2. Pinned Top-10 Evaluation Targets

All evaluation plans pin exact input checksums for the canonical Top-10 tailoring targets derived from `shortlist/tailoring_targets/targets.json` and `config/master_profile.yaml`:

- **Master Profile Checksum (`config/master_profile.yaml`):**
  `6412c9fd6e7ea390c64a7c773c46afda74199de36966369afb6f79c746534c8d`

| Rank | Target ID | Job ID | Company | Role | JD File | SHA-256 Checksum |
| :---: | :--- | :---: | :--- | :--- | :--- | :--- |
| 1 | `zoom_4766` | 4766 | Zoom | Software Engineer - AI Platform | `01_Zoom_Software_Engineer_AI_Platform.txt` | `3cb0db9d4a8b3af912332a1d52213c52742cc7c73a29281f119ce807d3d3c72f` |
| 2 | `doordash_4608` | 4608 | DoorDash | Software Engineer - Backend Infrastructure | `02_DoorDash_Software_Engineer_Backend_Infrastru.txt` | `b39e57fb914bba84cab470e13e74fbc845681a6612ccd8ea461c036c7f39e548` |
| 3 | `idme_3981` | 3981 | ID.me | Senior Software Engineer - Identity Verification | `03_IDme_Senior_Software_Engineer_Identity_Veri.txt` | `4bb41c9a8b25ea211c49bfc0036775b1392f32057a3c3e729e8f11fc0c978f3a` |
| 4 | `tiktok_4164` | 4164 | TikTok | Software Engineer - Recommendation Architecture | `04_TikTok_Software_Engineer_Recommendation_Arch.txt` | `37d3962b02d5c59fd0ca91915cd2ba86e593938eec5866cb97443666365c6452` |
| 5 | `roadrunner_5027` | 5027 | Roadrunner | Full Stack / Backend Engineer | `05_Roadrunner_Full_Stack_Backend_Engineer.txt` | `5688e99db817f037164e826e83ec8b1e90d2b11259578f6c9e35f8fe68868ecb` |
| 6 | `lexisnexislegalprofessional_4987` | 4987 | LexisNexis Legal & Professional | Software Engineer III - Platform | `06_LexisNexis_Legal_Professional_Software_Engin.txt` | `28509077c88abd860271921b7ee7bcac1ee47f52e676539a8887ce492d4b2532` |
| 7 | `openai_4949` | 4949 | OpenAI | Software Engineer - Applied Emerging Talent | `07_OpenAI_Software_Engineer_Applied_Emerging_Talen.txt` | `22a740d9b3d353e2c26c2cea4cb9733c677c74b313955cff07da9aba624c2130` |
| 8 | `c3ai_4894` | 4894 | C3 AI | Software Engineer - Core Platform | `08_C3_AI_Software_Engineer_Core_Platform.txt` | `7b03db4b9387ab42e94da649b6cdd6f68ec18295cfd7f2795a49f5e18ee5b975` |
| 9 | `commure_4839` | 4839 | Commure | Senior Software Engineer - Healthcare Data Platform | `09_Commure_Senior_Software_Engineer_Healthcare.txt` | `a1336d0d0077d11118edc35638c8cfdada22ab7b46a61426866199404e294bd4` |
| 10 | `twitch_4182` | 4182 | Twitch | Software Engineer - Video Systems | `10_Twitch_Software_Engineer_Video_Systems.txt` | `da07be5a86568397b34dd45497ba1421236c51ea5e6fb0f0a2e0a533cccd5fc7` |

---

## 3. Evaluation Plans & Live Templates

Four plan assets are maintained under [evaluation/tailor2/plans/](file:///Users/himanshu_jain/aero/Resume_Finetune/job-pipeline-tailor2-evaluation-plans/evaluation/tailor2/plans/):

### 3.1. Single-Target OpenAI Smoke Testing
- **`openai_smoke_recorded.json`**:
  - Validated offline plan configuring a single target (`openai_4949`) with mock provider identities for recorded replay or dry-run validation.
  - Budget: Max 10 calls, $1.00 USD, 300s timeout.
- **`openai_smoke_live.template.json`**:
  - Live configuration template for OpenAI provider execution. Configured with model `gpt-4o`, deterministic temperature `0.0`, and budget bounds (max 20 calls, $2.00 USD, 600s timeout).

### 3.2. Full Top-10 Evaluation Plans
- **`top10_recorded.json`**:
  - Full 10-target evaluation plan covering all canonical Top-10 targets in rank order. Uses mock provider identities for replay against pre-recorded fixtures.
  - Budget: Max 100 calls, $10.00 USD, 1800s timeout.
- **`top10_live.template.json`**:
  - Live execution template for running all 10 targets with active LLM providers.
  - Budget: Max 120 calls, $15.00 USD, 3600s timeout.

---

## 4. Baseline & Reference Registry

The reference registry at [reference_registry.json](file:///Users/himanshu_jain/aero/Resume_Finetune/job-pipeline-tailor2-evaluation-plans/evaluation/tailor2/registry/reference_registry.json) tracks candidate and baseline resume variants across three categories:

1. **`manual_reference` (Human Ground Truth):**
   - Hand-crafted, recruiter-reviewed resumes built directly from canonical master profile facts.
   - Available target: **`openai_4949`** (referenced on branch `origin/resume/openai-4949-manual` at commit prefix `a4dd50b`, including `.tex`, `.pdf`, `PROVENANCE.md`, and `RECRUITER_REVIEW.md`).
   - Other 9 targets are marked `is_available: false` pending future human crafting.
2. **`tailor1_legacy` (Historical Pipeline):**
   - Single-stage LLM output without audit-repair loop, multi-candidate ranking, or render-fill balancing.
   - All targets are currently marked `is_available: false` pending structured ingestion into the evaluation store.
3. **`future_render_fill` (Phase 4 Layout Optimizer):**
   - Render-measure-expand-compress candidate resumes.
   - All targets are marked `is_available: false` until Phase 4 implementation is integrated.

---

## 5. Human Blind Review Framework

To eliminate reviewer bias, comparative evaluation uses a double-blind A/B testing protocol:

- **Seeded Blind Shuffling:** `candidate_a` and `candidate_b` are assigned randomly via deterministic seeding. Model names, prompt strategies, and pipeline version tags are completely hidden from reviewers.
- **Review Assets:**
  - [instructions.md](file:///Users/himanshu_jain/aero/Resume_Finetune/job-pipeline-tailor2-evaluation-plans/evaluation/tailor2/human_review/instructions.md): Step-by-step review workflow, 6-second scan guidelines, confidence rating definitions, and `TIE` vs. `NEITHER` criteria.
  - [rubric_dictionary.json](file:///Users/himanshu_jain/aero/Resume_Finetune/job-pipeline-tailor2-evaluation-plans/evaluation/tailor2/human_review/rubric_dictionary.json): Formal definitions, positive indicators, and negative indicators for all 14 rubric dimensions.
  - [response_template.json](file:///Users/himanshu_jain/aero/Resume_Finetune/job-pipeline-tailor2-evaluation-plans/evaluation/tailor2/human_review/response_template.json): Valid JSON template conforming to `HumanReviewResponse` schema.
  - [factual_error_guidance.md](file:///Users/himanshu_jain/aero/Resume_Finetune/job-pipeline-tailor2-evaluation-plans/evaluation/tailor2/human_review/factual_error_guidance.md): Strict zero-tolerance audit checklist covering employer title changes, metric distortions, and technology inventions.

### Rubric Dimensions
The 14 evaluation dimensions defined in `src.tailor2_eval.schemas.RUBRIC_DIMENSIONS`:
1. `factual_trustworthiness` (Critical)
2. `target_role_fit` (High)
3. `recruiter_scan_quality` (High)
4. `clarity` (High)
5. `achievement_strength` (High)
6. `metric_interpretability` (High)
7. `interview_defensibility` (Critical)
8. `mechanism_outcome_balance` (Medium)
9. `redundancy` (Medium)
10. `ai_slop` (High)
11. `skills_credibility` (Medium)
12. `visual_readability` (High)
13. `page_utilization` (Critical)
14. `overall_preference` (Critical)

---

## 6. Proposed Release Gates

The following quality thresholds are proposed for production acceptance of Tailor2 candidate models (`ReleaseGateDecision`, `is_established_policy: false`):

| Gate Criterion ID | Description | Required Threshold | Rationale |
| :--- | :--- | :---: | :--- |
| `zero_fatal_integrity_findings` | Zero fatal integrity findings (no hallucinations, no title mutations, no ungrounded claims) | `fatal_integrity_rate == 0.00` | Absolute zero tolerance for resume fraud or unevidenced metrics. |
| `usable_artifact_rate` | Usable artifact rate (status `ACCEPTED` or `ACCEPTED_WITH_WARNINGS`) | $\ge 90\%$ | At least 9 of 10 targets must produce valid, deployable resumes. |
| `one_page_compliance` | Strict 1-page layout compliance | `one_page_success_rate == 1.00` | Resumes must never spill onto page 2. |
| `layout_warning_budget` | Bounded layout warnings (widows, tight spacing, visual crowding) | $\le 10\%$ | Maintains professional typesetting standards. |
| `human_preference_win_rate` | Candidate win rate over baseline in human blind review | $\ge 60\%$ (non-tie) | Demonstrates clear human-judged quality improvement over legacy outputs. |
| `zero_human_factual_errors` | Zero factual errors reported by human reviewers | `factual_error_report_count == 0` | Secondary human audit gate confirming machine verification. |
| `call_budget_discipline` | Average provider calls per target | $\le 4.0$ calls | Ensures bounded latency and cost (draft + audit + max 1 repair + re-audit). |
| `cost_budget_discipline` | Average LLM cost per tailored resume | $\le \$0.50$ USD | Economical batch tailoring operation. |
| `latency_budget_discipline` | Average wall-clock latency per target | $\le 60.0$ s | Responsive user experience. |

---

## 7. Operational Evaluation Commands

The offline evaluation harness is operated via `scripts/evaluate_tailor2.py`:

### 7.1. Validating a Plan File
Validates structural schema, absence of credential keys, and checks that pinned SHA-256 checksums match files on disk:
```bash
python -m scripts.evaluate_tailor2 validate-plan evaluation/tailor2/plans/top10_recorded.json
```

### 7.2. Dry-Run Execution (Offline Verification)
Verifies input readability and target resolution without making provider calls or spending budget:
```bash
python -m scripts.evaluate_tailor2 run evaluation/tailor2/plans/top10_recorded.json --dry-run
```

### 7.3. Recorded Replay Execution
Executes the evaluation loop using pre-recorded provider responses:
```bash
python -m scripts.evaluate_tailor2 run evaluation/tailor2/plans/top10_recorded.json --recorded tests/fixtures/tailor2_eval/
```

### 7.4. Building Blind Comparison Pairs
Generates randomized A/B pairs with hashed/anonymized identifiers for human review:
```bash
python -m scripts.evaluate_tailor2 build-blind-pairs artifacts/evaluation/tailor2/top10_recorded/ --out-dir data/blind_pairs/
```

### 7.5. Aggregating Results & Evaluating Release Gates
Computes aggregate metrics, evaluates against proposed release gates, and generates markdown and JSON reports:
```bash
python -m scripts.evaluate_tailor2 aggregate artifacts/evaluation/tailor2/top10_recorded/ --plan-id top10_recorded --out-dir reports/top10_recorded/
```

### 7.6. Live Execution Safety Guardrail
Live execution is strictly guarded:
```bash
# This command will deliberately raise LiveModeNotAuthorizedError or NotImplementedError unless
# live execution is explicitly implemented and credentials are provided via environment variables.
python -m scripts.evaluate_tailor2 run evaluation/tailor2/plans/top10_live.template.json --live
```

---

## 8. Handoff & Next Steps

1. **Integration with Phase 4 (Render-Fill Optimizer):**
   - Once the layout expand-compress engine is finalized, populate the `future_render_fill` entries in [reference_registry.json](file:///Users/himanshu_jain/aero/Resume_Finetune/job-pipeline-tailor2-evaluation-plans/evaluation/tailor2/registry/reference_registry.json).
2. **Phase 5 (Live Evaluation & Human Review):**
   - Copy `evaluation/tailor2/plans/top10_live.template.json` to a local run plan.
   - Execute live evaluation under strict budget caps.
   - Run `build-blind-pairs` and distribute review packets with [instructions.md](file:///Users/himanshu_jain/aero/Resume_Finetune/job-pipeline-tailor2-evaluation-plans/evaluation/tailor2/human_review/instructions.md).
   - Ingest completed human review JSONs and generate the release gate decision report.
