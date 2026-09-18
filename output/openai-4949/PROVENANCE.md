# Bullet-to-Evidence Provenance — OpenAI Applied Emerging Talent (job 4949)

**Canonical profile hash (this revision):** `config/master_profile.yaml` SHA-256 =
`2bf6c44ef08ced7d18e2a5a69587af50f1b8a2f44beb808dd5460b8f0124a274`, verified against the
attached canonical file before any edit was made. All bullet ids, evidence strings, and
metric values below are read from this exact file.

Every row maps a rendered bullet to its `master_profile.yaml` bullet id(s) and claim type.
"Rewritten" means the wording was substantively changed from the profile's stored
`medium` phrasing to fix a writing-standard violation (semicolon chain, banned internal
term, length, grammatical parallelism, or an inaccurate characterization) while preserving
every fact and metric; "as-is" means the phrasing is the profile's `medium` variant with
only LaTeX escaping applied.

## Revision 2 changes (this cycle)

Five bullets were revised on top of the original draft; everything else on the résumé is
unchanged from commit `faa29c1`.

## Experience — MalyTech (Software Engineering Intern)

| Rendered bullet (short form) | Source id | claim_type | Change |
|---|---|---|---|
| Four async Python adapters + non-blocking orchestrator, five services | `int_b1` | verified | **rewritten (rev. 2)** — the prior phrasing ended abruptly on "five asynchronous Python microservices in all." Rewritten to lead with concrete nouns (four adapters, one orchestrator) and fold the five-service count into the closing clause. Every noun verified against `int_b1.evidence`: "Four adapter services: gab_sms (telecom), pesalink (PesaLink network), gab_iprs (IPRS registry), OMNI/CIP (Infrasoft AML); one Core onboarding service orchestrating three of them" and "Core ingress: ... returning 202 Accepted without blocking on any third party" (non-blocking). Provider domains ("messaging, payments, identity-verification, and AML") map 1:1 to the four adapters' evidenced domains. |
| Idempotent transfer engine, PostgreSQL reservations, 8 concurrent -> 1 call | `int_b2` | verified | as-is (unchanged since rev. 1) |
| Fail-closed AML gateway, unified REST/SOAP, credential isolation/PII redaction/XML defenses | `int_b3` | verified | **rewritten (rev. 2)** — rev. 1's phrasing had broken grammatical parallelism ("serving both REST/JSON and legacy SOAP/XML through shared orchestration and hardened with..."). Rewritten as three parallel verb clauses (returned / unified / enforced). Verified against `int_b3.evidence`: "Dual ingress: POST /api/v1/screening (JSON) and POST /services/NameScreening (SOAP getCIPMatch) over one orchestration layer" (-> "unified"), "Typed error map: AML_UNAVAILABLE / AML_FAULT / AML_BAD_RESPONSE -> 502" (-> "returned typed errors on provider faults"), and the credential-isolation/PII-redaction/XML-injection evidence lines (unchanged from rev. 1). |

## Experience — Amdocs Ltd. (Software Developer)

Unchanged from rev. 1 — not in scope for this revision cycle.

| Rendered bullet (short form) | Source id | claim_type | Change |
|---|---|---|---|
| Kafka DLQ consolidation, 70% / ~80% | `am_b01` | verified | as-is since rev. 1 |
| Row-level entitlement, JWT -> N1QL/Elasticsearch predicates | `am_b02` | verified | as-is since rev. 1 |
| Audit trail, ~60% issue-resolution time | `am_b03` | estimated (user-approved 2026-08-03) | as-is since rev. 1 |
| Data retention, ~40% footprint / ~25% latency | `am_b04` | estimated (user-approved 2026-08-03) | as-is since rev. 1 |
| Test automation, ~50% effort / ~40% defects | `am_b05` | estimated (user-approved 2026-08-03) | as-is since rev. 1 |
| *(dropped)* generic Order Management domain bullet | `am_b00` | verified | dropped in rev. 1, still dropped |
| *(dropped)* JUnit/SonarQube coverage bullet | `am_b07` | verified | dropped in rev. 1, still dropped |

## Projects — ResumeFinetune (listed first per instruction)

| Rendered bullet (short form) | Source id(s) | claim_type | Change |
|---|---|---|---|
| Deterministic pipeline, ATS resolvers, typed eligibility gates, 3,212/2,019/164 | `rft_b01_ingestion_scale` + `rft_b02_eligibility_engine` + `rft_b03_resolution_runtime` | verified (all three) | **rewritten (rev. 2) — now a 3-evidence merge, replacing the rev. 1 bullet that cited only `rft_b01`.** "3,212 listings" / "2,019 job descriptions" / "164 qualifying roles" / "seven-day discovery window" trace to `rft_b01.evidence` ("review/2026-09-08-ingest/REPORT.md sections 3, 4, and 6: run 22 timing, 3,212 discovered ... 2,019 resolved, and 164 qualifying"). "Typed eligibility gates" traces to `rft_b02.evidence` ("src/eligibility.py and src/prefilter.py: pure typed classifier plus pre- and post-resolution gate adapters"). "ATS-specific resolvers" traces to `rft_b03.evidence` ("src/resolve/: router and dedicated Greenhouse, Lever, Ashby, Workday, Amazon Jobs, Jobright ... modules"). Per `rft_b01.interview_risk`, the bullet says "seven-day discovery window" (not "posted within seven days") and does not claim the 2,019 resolutions are limited to the 3,212 newly discovered rows — they are stated as parallel counts, not a subset relationship, because `rft_b01.interview_risk` explicitly notes "The 2,019 resolutions include existing July backlog, not only the 3,176 rows newly inserted in September." |
| Cut LLM scoring movement 0.67->0.20, schema/row-coverage validation, transactional score import | `rft_b06_scoring_stability` | verified | **rewritten (rev. 2)** — rev. 1 ended with "importing results into the production database," which overstated what the evidence supports. Corrected to "enforced schema and row-coverage validation before transactional score import," tracing exactly to `rft_b06.evidence`: "scripts/import_scores.py: strict schema, row-coverage validation, and transactional database update." The bullet does not call the scorer deterministic and does not claim the metric proves ranking accuracy, per `rft_b06.interview_risk` ("This reduces run-to-run instability but does not establish ranking accuracy... Do not call the scorer deterministic"). |
| Resumable evidence-grounded tailoring workflow, approved profile evidence, separate LLM review, human approval | `rft_b08_tailoring_orchestration` + `rft_b09_jd_provenance` | verified (both) | **rewritten (rev. 2)** — replaces rev. 1's version, which was still partially a stage inventory. "Resumable ... tailoring workflow" and "deterministic validation" trace to `rft_b08.evidence` ("src/tailor/pilot.py: resumable S1, S0, S2, S3, G2, render, and G3 orchestration with per-stage manifests"; the deterministic-lint step). "Approved profile evidence" combines `rft_b08`'s evidence-selection step with `rft_b09.evidence` ("src/tailor/provenance.py: typed provenance states, canonical fingerprints, content hashes, and database verification"). Internal stage names (S1/S0/S2/S3/G2) are not exposed, per instruction. |

### Separate LLM review vs. a different auditor model

The bullet says **"a separate LLM review,"** not "an independent model" or "a different
auditor model." `rft_b08.evidence` documents an independent *critique step* in the
pipeline (a distinct invocation from the drafting step) but does not establish that the
critique invocation uses a different model family than the drafting invocation — both may
run on the same underlying provider/model depending on configuration. "Separate" describes
the pipeline stage being a distinct call; it makes no claim about model diversity. This
distinction is preserved from the instruction and is intentional, not an oversight.

## Projects — Fake Review Detection on Yelp

Unchanged from rev. 1 — not in scope for this revision cycle.

| Rendered bullet (short form) | Source id | claim_type | Change |
|---|---|---|---|
| PySpark ETL, 608K reviews, 260K/5K profiles, Delta Lake | `frd_b1` | verified | as-is since rev. 1 |
| DeBERTa fine-tune, 423K reviews, 0.93 ROC-AUC / 0.84 macro-F1 | `frd_b2` | verified | as-is since rev. 1 |

## Projects — Campus Marketplace

Unchanged from rev. 1 — not in scope for this revision cycle.

| Rendered bullet (short form) | Source id | claim_type | Change |
|---|---|---|---|
| Backend, primary developer on 3-person team, Java 21/Spring Boot/Flyway-PostgreSQL | `cm_b1` | scoped | as-is since rev. 1 |

## Technical Skills

Unchanged from rev. 1, per instruction to keep the existing role-focused skills strategy.

| Category | Terms | Source |
|---|---|---|
| AI and Machine Learning | Agentic AI, LLM Orchestration, LLM Evaluation, Prompt Engineering, Structured Outputs, Human-in-the-Loop Systems | User-specified precise term list; each term is demonstrated by a rendered bullet above (LLM Orchestration/Evaluation and Structured Outputs by the `rft_b06` scoring-stability bullet's schema/transactional-import language; Human-in-the-Loop by the `rft_b08`/`rft_b09` bullet's human-approval clause). The canonical profile's own `keywords.exact` list for ResumeFinetune (line 187-190) independently confirms "agentic AI," "LLM orchestration," "LLM evaluation," "prompt engineering," "structured outputs," and "human-in-the-loop" as profile-recognized terms for this project. |
| Languages | Java, Python, C++, SQL | `master_profile.yaml` top-level `skills.languages`, unchanged |
| Backend and Data | Spring Boot, FastAPI, PostgreSQL, Apache Kafka, RabbitMQ, Elasticsearch, PySpark, PyTorch | Union of `tech.primary`/`tech.secondary` across MalyTech, Amdocs, and the two AI/ML projects actually rendered |
| Developer Tools | Jenkins, Docker, Git/GitHub, Postman, OpenShift, SonarQube | Subset of `skills.developer_tools` retained only where a rendered bullet or entry's `keywords.exact` evidences it; dropped `Bitbucket`, `Maven`, `IntelliJ` as not evidenced by anything shown on this version |

## Not used on this résumé

- `sepsis_early_warning`, `clinical_trial_platform` — not part of either base variant for this
  role and not raised by the user's instructions; excluded to keep the page to the strongest
  three projects.
- `peerchat_peer_discovery` — evaluated and excluded; see RECRUITER_REVIEW.md "Project
  selection" for the full reasoning (unchanged from rev. 1).
- `am_b06_aws_ci_transition`, `am_b08_human_task_resilience` — priority-3 Amdocs bullets,
  excluded once the 5-bullet cap was filled by stronger priority-1 metric bullets.
- `int_b4` through `int_b9` — priority-2/3 MalyTech bullets, excluded by the fixed 3-bullet
  cap; `int_b1`/`int_b2`/`int_b3` are all priority-1.
- `rft_b04`, `rft_b05`, `rft_b07`, `rft_b10` through `rft_b15` — priority-1/2 ResumeFinetune
  bullets not selected; the three rendered bullets (now backed by five evidence ids total:
  `rft_b01`, `rft_b02`, `rft_b03`, `rft_b06`, `rft_b08`, `rft_b09`) were judged the strongest
  combination for a 3-bullet budget on this JD.
