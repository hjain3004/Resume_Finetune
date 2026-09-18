# Bullet-to-Evidence Provenance — OpenAI Applied Emerging Talent (job 4949)

Every row maps a rendered bullet to its `master_profile.yaml` bullet id and claim type.
"Rewritten" means the wording was substantively changed from the profile's stored
`medium` phrasing to fix a writing-standard violation (semicolon chain, banned internal
term, or length) while preserving every fact and metric; "as-is" means the phrasing is the
profile's `medium` variant with only LaTeX escaping applied.

## Experience — MalyTech (Software Engineering Intern)

| Rendered bullet (short form) | Source id | claim_type | Change |
|---|---|---|---|
| Anti-corruption layer + Core onboarding service, five async microservices | `int_b1` | verified | as-is |
| Idempotent transfer engine, PostgreSQL reservations, 8 concurrent -> 1 call | `int_b2` | verified | as-is |
| Fail-closed AML gateway, REST+SOAP, credential isolation/PII redaction | `int_b3` | verified | rewritten — removed a semicolon chain and dropped "XML-injection resistance" phrasing that duplicated a separate clause; folded into one flowing sentence per the no-semicolon writing standard |

## Experience — Amdocs Ltd. (Software Developer)

| Rendered bullet (short form) | Source id | claim_type | Change |
|---|---|---|---|
| Kafka DLQ consolidation, 70% / ~80% | `am_b01` | verified | rewritten — replaced "Helm binding function" with "Helm rollout" because "binding function" is a banned internal term list entry; metrics and mechanism otherwise unchanged |
| Row-level entitlement, JWT -> N1QL/Elasticsearch predicates | `am_b02` | verified | as-is |
| Audit trail, ~60% issue-resolution time | `am_b03` | estimated (user-approved 2026-08-03) | as-is (verb changed "Cut" -> "Shortened" for variety only) |
| Data retention, ~40% footprint / ~25% latency | `am_b04` | estimated (user-approved 2026-08-03) | as-is |
| Test automation, ~50% effort / ~40% defects | `am_b05` | estimated (user-approved 2026-08-03) | as-is (verb changed "Reduced" -> "Lowered" for variety only) |
| *(dropped)* generic Order Management domain bullet | `am_b00` | verified | dropped — no metric, weakest of the six priority-1 Amdocs bullets, needed to meet the "5 strongest bullets" cap |
| *(dropped)* JUnit/SonarQube coverage bullet | `am_b07` | verified | dropped — same reason; also carries the "90% coverage" framing flagged as a vanity-metric risk in the profile's own interview_risk note |

## Projects — ResumeFinetune (listed first per instruction)

| Rendered bullet (short form) | Source id | claim_type | Change |
|---|---|---|---|
| 3,212 postings, 2,019 resolved, 164 qualifying, 1h43m | `rft_b01` | verified | rewritten — shortened from the profile's 3-clause `medium` phrasing (dropped the "3,176 inserted" sub-detail) to fit two rendered lines; "seven-day discovery window" wording preserved exactly per the profile's own interview_risk caution |
| 0.67 -> 0.20 scoring drift via 3-pass self-consistency | `rft_b06` | verified | rewritten — same facts and metrics as the `medium` phrasing, condensed to one sentence |
| Resumable agentic workflow, evidence-grounded draft, human approval gate | `rft_b08` (+ `rft_b09` provenance concept) | verified | rewritten from scratch to remove internal stage names (S1/S0/S2/S3/G2) per the explicit instruction not to expose them; every remaining noun phrase (typed stage contracts = per-stage orchestration, deterministic claim validation = the C1/lint contract, independent LLM review = the critique step, human approval = the review packet) maps to `rft_b08`'s evidence list |

## Projects — Fake Review Detection on Yelp

| Rendered bullet (short form) | Source id | claim_type | Change |
|---|---|---|---|
| PySpark ETL, 608K reviews, 260K/5K profiles, Delta Lake | `frd_b1` | verified | rewritten — condensed, dropped "six-stage pipeline" framing (not needed once presented as a standalone project bullet) |
| DeBERTa fine-tune, 423K reviews, 0.93 ROC-AUC / 0.84 macro-F1 | `frd_b2` | verified | as-is |

## Projects — Campus Marketplace

| Rendered bullet (short form) | Source id | claim_type | Change |
|---|---|---|---|
| Backend, primary developer on 3-person team, Java 21/Spring Boot/Flyway-PostgreSQL | `cm_b1` | scoped | as-is |

## Technical Skills

| Category | Terms | Source |
|---|---|---|
| AI and Machine Learning | Agentic AI, LLM Orchestration, LLM Evaluation, Prompt Engineering, Structured Outputs, Human-in-the-Loop Systems | User-specified precise term list; each term is demonstrated by a rendered bullet above (LLM Orchestration/Evaluation by `rft_b06`'s evidence, Structured Outputs by `rft_b06`'s schema-validated import, Human-in-the-Loop by `rft_b08`'s human approval gate) |
| Languages | Java, Python, C++, SQL | `master_profile.yaml` top-level `skills.languages`, unchanged |
| Backend and Data | Spring Boot, FastAPI, PostgreSQL, Apache Kafka, RabbitMQ, Elasticsearch, PySpark, PyTorch | Union of `tech.primary`/`tech.secondary` across MalyTech, Amdocs, and the two AI/ML projects actually rendered |
| Developer Tools | Jenkins, Docker, Git/GitHub, Postman, OpenShift, SonarQube | Subset of `skills.developer_tools` retained only where a rendered bullet or entry's `keywords.exact` evidences it; dropped `Bitbucket`, `Maven`, `IntelliJ` as not evidenced by anything shown on this version |

## Not used on this résumé

- `sepsis_early_warning`, `clinical_trial_platform` — not part of either base variant for this
  role and not raised by the user's instructions; excluded to keep the page to the strongest
  three projects.
- `peerchat_peer_discovery` — evaluated and excluded; see RECRUITER_REVIEW.md "Project
  selection" for the full reasoning.
- `am_b06_aws_ci_transition`, `am_b08_human_task_resilience` — priority-3 Amdocs bullets,
  excluded once the 5-bullet cap was filled by stronger priority-1 metric bullets.
- `int_b4` through `int_b9` — priority-2/3 MalyTech bullets, excluded by the fixed 3-bullet
  cap; `int_b1`/`int_b2`/`int_b3` are all priority-1.
