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

## Revision 2 changes

Five bullets were revised on top of the original draft; everything else on the résumé was
unchanged from commit `faa29c1`.

## Revision 3 changes (this cycle — density maximization)

The user explicitly overrode the prior whitespace-preservation guidance: "maximize
defensible, recruiter-relevant content" rather than stop at a conservative bullet count.
Changes this cycle:
- Campus Marketplace **removed entirely**; replaced with PeerChat (`pc_b01`, `pc_b02`).
- Added a 4th ResumeFinetune bullet (`rft_b07_model_authority_boundary`).
- Restored a 6th Amdocs bullet (`am_b07_code_quality_gates`).
- Added a 5th ResumeFinetune bullet (`rft_b09_jd_provenance`).
- **Rejected** a 6th ResumeFinetune bullet (`rft_b12_audit_framework`) — see "Candidate
  rejected" below. Margins moved from 0.35in to 0.30in (the instructed floor) to
  accommodate the accepted additions; vertical spacing in the itemize/heading macros was
  tightened once, safely, and verified with no overlap.
- The Amdocs title ("Software Developer" -> "Software Engineer") requested in the same
  message was **held, not applied** — see "Title change held" below.

Final bullet count: 3 MalyTech + 6 Amdocs + 5 ResumeFinetune + 2 Fake Review Detection +
2 PeerChat = **18 bullets**, one page, 11pt, 0.30in margins, zero LaTeX overflow.

### Title change held

The instruction asked to change Amdocs' title from "Software Developer" to "Software
Engineer." The canonical profile marks this field `# NEVER altered. Target-title seeding
happens in the summary line only.` and its own `known_gaps.am_gap_title_mismatch` states:
"altering it is resume fraud, not tailoring." This is the candidate's actual, verifiable
former job title (the kind a reference or background check confirms), not a stylistic
choice, so it was flagged back to the user rather than silently applied or silently
skipped. **The rendered résumé still says "Software Developer."** If the user confirms
the change, it is a one-line edit; not applied speculatively here because reference/
background-check exposure from a wrong assumption is high-cost and hard to undo once a
résumé carrying it has been submitted.

### Candidate rejected: `rft_b12_audit_framework`

Added, compiled, and visually inspected per instruction ("Add candidates one at a time,
recompiling and visually inspecting the PDF after each addition"). At the 0.30in margin
floor with the already-applied safe spacing tightening, this candidate required a second,
more aggressive tightening pass to fit on one page. That pass produced visible text
overlap: the MalyTech AML-gateway bullet's last line touched the "Software Developer"
experience heading below it, the ResumeFinetune heading touched its first bullet, the FRD
macro-F1 line touched the PeerChat heading below it, and the new bullet's second line
touched the Fake Review Detection heading below it. This matches the explicit stop
condition "cause clipping, overlap, or LaTeX overflow." The over-tightened spacing was
reverted to the prior safe values and `rft_b12` was removed, restoring the clean 18-bullet,
one-page, zero-overlap state confirmed by the final visual QA pass.

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
| 90% unit-test coverage, JUnit 5/Mockito/WireMock, ~500 SonarQube findings | `am_b07` | verified | **restored (rev. 3)** — dropped in rev. 1 to meet the then-5-bullet cap; re-added as the 6th bullet under the rev. 3 density-maximization instruction. Wording follows the user's suggested rendering, changing "deployment quality gates" (rev. 1's phrasing, since this bullet wasn't rendered then) to "build-time quality gates," which is the more precise match to `am_b07.evidence`: "Jenkins quality gates failing builds on new-code coverage and new critical issues." |
| *(dropped)* generic Order Management domain bullet | `am_b00` | verified | dropped in rev. 1, still dropped — weakest of the priority-1 Amdocs bullets, no metric |

## Projects — ResumeFinetune (listed first per instruction)

| Rendered bullet (short form) | Source id(s) | claim_type | Change |
|---|---|---|---|
| Deterministic pipeline, ATS resolvers, typed eligibility gates, 3,212/2,019/164 | `rft_b01_ingestion_scale` + `rft_b02_eligibility_engine` + `rft_b03_resolution_runtime` | verified (all three) | **rewritten (rev. 2) — now a 3-evidence merge, replacing the rev. 1 bullet that cited only `rft_b01`.** "3,212 listings" / "2,019 job descriptions" / "164 qualifying roles" / "seven-day discovery window" trace to `rft_b01.evidence` ("review/2026-09-08-ingest/REPORT.md sections 3, 4, and 6: run 22 timing, 3,212 discovered ... 2,019 resolved, and 164 qualifying"). "Typed eligibility gates" traces to `rft_b02.evidence` ("src/eligibility.py and src/prefilter.py: pure typed classifier plus pre- and post-resolution gate adapters"). "ATS-specific resolvers" traces to `rft_b03.evidence` ("src/resolve/: router and dedicated Greenhouse, Lever, Ashby, Workday, Amazon Jobs, Jobright ... modules"). Per `rft_b01.interview_risk`, the bullet says "seven-day discovery window" (not "posted within seven days") and does not claim the 2,019 resolutions are limited to the 3,212 newly discovered rows — they are stated as parallel counts, not a subset relationship, because `rft_b01.interview_risk` explicitly notes "The 2,019 resolutions include existing July backlog, not only the 3,176 rows newly inserted in September." |
| Cut LLM scoring movement 0.67->0.20, schema/row-coverage validation, transactional score import | `rft_b06_scoring_stability` | verified | **rewritten (rev. 2)** — rev. 1 ended with "importing results into the production database," which overstated what the evidence supports. Corrected to "enforced schema and row-coverage validation before transactional score import," tracing exactly to `rft_b06.evidence`: "scripts/import_scores.py: strict schema, row-coverage validation, and transactional database update." The bullet does not call the scorer deterministic and does not claim the metric proves ranking accuracy, per `rft_b06.interview_risk` ("This reduces run-to-run instability but does not establish ranking accuracy... Do not call the scorer deterministic"). |
| Resumable evidence-grounded tailoring workflow, approved profile evidence, separate LLM review, human approval | `rft_b08_tailoring_orchestration` + `rft_b09_jd_provenance` (conceptual overlap; `rft_b09` gets its own full bullet in rev. 3, see below) | verified (both) | **rewritten (rev. 2)** — replaces rev. 1's version, which was still partially a stage inventory. "Resumable ... tailoring workflow" and "deterministic validation" trace to `rft_b08.evidence` ("src/tailor/pilot.py: resumable S1, S0, S2, S3, G2, render, and G3 orchestration with per-stage manifests"; the deterministic-lint step). "Approved profile evidence" combines `rft_b08`'s evidence-selection step with `rft_b09.evidence` ("src/tailor/provenance.py: typed provenance states, canonical fingerprints, content hashes, and database verification"). Internal stage names (S1/S0/S2/S3/G2) are not exposed, per instruction. |
| Isolated LLMs behind least-authority tool-free boundary, no repo/database access, deterministic Python owns every write | `rft_b07_model_authority_boundary` | verified | **added (rev. 3)**, wording follows the user's suggested rendering almost verbatim. Traces to `rft_b07.evidence`: "scripts/score_batch.py module contract: prompt content embedded directly; nested scorer has zero filesystem authority," "src/tailor/invoke.py and src/tailor/providers.py: tool-disabled Claude invocation and direct tool-free Gemini/OpenAI HTTP calls," "src/llm_trace.py: wrapper-owned immutable invocation traces." Matches `rft_b07.medium` almost exactly ("Contained LLMs behind a least-authority text-in/text-out boundary with no database or repository access, while deterministic Python owned schema validation, trace capture, and every filesystem and SQLite write") — "database write" is used in place of "SQLite write" for generality; both are accurate since SQLite is the database in question. |
| Fail-closed JD provenance, content hashes, source/ATS metadata, database verification or user attestation, blocks aggregator summaries | `rft_b09_jd_provenance` | verified | **added (rev. 3)** as its own full bullet (previously only contributed a concept to the rft_b08 bullet in rev. 2). Wording follows the user's suggested rendering, matching `rft_b09.medium` closely: "Enforced a fail-closed JD provenance boundary that binds content hashes, source and ATS metadata, and database verification or user attestation into each run, blocking aggregator summaries and manifest drift." "Unverified" was added before "aggregator summaries" for clarity; this is consistent with `rft_b09.interview_risk`'s distinction between attested-but-unverified and database-verified provenance states. |

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

## Projects — PeerChat (rev. 3, replaces Campus Marketplace)

Campus Marketplace (`cm_b1`) was removed entirely per rev. 3 instruction. PeerChat now
occupies its slot with the two strongest `verified` (not `scoped`) PeerChat bullets.

| Rendered bullet (short form) | Source id | claim_type | Change |
|---|---|---|---|
| Event-driven membership layer, append-only event log, deterministic snapshot projection | `pc_b01_event_sourcing` | verified | **added (rev. 3)**, as-is from `pc_b01.medium` with LaTeX escaping only. Priority 1, marked in the profile as "lead bullet; almost always selected." Evidence: "peer_discovery/membership/event_log.py: monotonic seq_no, RLock-guarded append" and "peer_discovery/membership/snapshot.py: apply_event with _ALLOWED_FROM_STATES guards." |
| Gossip dissemination, LRU dedup, SWIM-inspired failure detection, trust-on-first-use key exchange over WebSockets | `pc_b02_network_layer` | verified | **added (rev. 3), rewritten to remove a colon fragment.** `pc_b02.medium` reads "Implemented the network layer: gossip dissemination with LRU-backed dedup..." — a colon fragment against the writing standard. Rewritten as one flowing sentence with identical facts. "SWIM-inspired" is preserved verbatim and NOT upgraded to "SWIM-style"/"SWIM implementation," per `pc_b02.interview_risk`'s explicit caution that this system broadcasts every heartbeat to every peer (full mesh) and only borrows SWIM's two-phase suspicion timer, not its randomized probing. Evidence: "peer_discovery/network/gossip.py: MAX_SEEN_EVENTS = 10_000," "peer_discovery/membership/presence.py: ACTIVE -> SUSPECTED -> DISCONNECTED," "peer_discovery/network/discovery_node.py: lazy_register_pubkey ... idempotent." |

`pc_b04_transport_consolidation` (also priority 1) was considered and not used: its
`claim_type` is `scoped`, not `verified`, and the instruction specifically asked for "the
strongest two verified PeerChat bullets."

## Technical Skills

Unchanged from rev. 1, per instruction to keep the existing role-focused skills strategy.

| Category | Terms | Source |
|---|---|---|
| AI and Machine Learning | Agentic AI, LLM Orchestration, LLM Evaluation, Prompt Engineering, Structured Outputs, Human-in-the-Loop Systems | User-specified precise term list; each term is demonstrated by a rendered bullet above (LLM Orchestration/Evaluation and Structured Outputs by the `rft_b06` scoring-stability bullet's schema/transactional-import language; Human-in-the-Loop by the `rft_b08`/`rft_b09` bullet's human-approval clause). The canonical profile's own `keywords.exact` list for ResumeFinetune (line 187-190) independently confirms "agentic AI," "LLM orchestration," "LLM evaluation," "prompt engineering," "structured outputs," and "human-in-the-loop" as profile-recognized terms for this project. |
| Languages | Java, Python, C++, SQL | `master_profile.yaml` top-level `skills.languages`, unchanged |
| Backend and Data | Spring Boot, FastAPI, PostgreSQL, Apache Kafka, RabbitMQ, Elasticsearch, PySpark, PyTorch | Union of `tech.primary`/`tech.secondary` across MalyTech, Amdocs, and the two AI/ML projects actually rendered |
| Developer Tools | Jenkins, Docker, Git/GitHub, Postman, OpenShift, SonarQube | Subset of `skills.developer_tools` retained only where a rendered bullet or entry's `keywords.exact` evidences it; dropped `Bitbucket`, `Maven`, `IntelliJ` as not evidenced by anything shown on this version |

## Not used on this résumé (as of rev. 3)

- `sepsis_early_warning`, `clinical_trial_platform` — not part of either base variant for this
  role and not raised in any instruction; still excluded.
- `campus_marketplace` (`cm_b1` through `cm_b5`) — **removed entirely in rev. 3** per explicit
  instruction, replaced by PeerChat.
- `pc_b03_testing_rigor` (priority 2), `pc_b04_transport_consolidation` (priority 1 but
  `scoped`, not `verified`), `pc_b05_tofu_bootstrap` (priority 3) — PeerChat bullets not
  selected; `pc_b01`/`pc_b02` are the two strongest `verified` bullets, per instruction.
- `am_b06_aws_ci_transition`, `am_b08_human_task_resilience` — priority-3 Amdocs bullets,
  still excluded; `am_b00` also excluded (weakest priority-1 bullet, no metric). Amdocs is
  now at 6 bullets (`am_b01`-`am_b05` + `am_b07`), the maximum reachable without the page
  breaking, per the rev. 3 candidate-by-candidate compile-and-inspect process.
- `int_b4` through `int_b9` — priority-2/3 MalyTech bullets, excluded by the fixed 3-bullet
  cap; `int_b1`/`int_b2`/`int_b3` are all priority-1.
- `rft_b04_idempotent_lifecycle`, `rft_b05_duplicate_clustering`, `rft_b10_atomic_publication`
  through `rft_b11_multi_provider` — ResumeFinetune bullets not selected; not attempted in the
  rev. 3 candidate loop because the four higher-priority instructed candidates (`rft_b07`,
  restored `am_b07`, `rft_b09`, then `rft_b12`) already reached the page's safe limit.
- `rft_b12_audit_framework` — **attempted and rejected in rev. 3**; see "Candidate rejected"
  above. ResumeFinetune is at 5 bullets (`rft_b01`+`rft_b02`+`rft_b03` merged into bullet 1,
  `rft_b06`, `rft_b08`+`rft_b09`-concept merged into bullet 3, `rft_b07`, `rft_b09` as its own
  bullet 5), the maximum reachable without overlap at the 0.30in margin floor.
- `rft_b13_research_banks`, `rft_b14_agentic_discovery_design`, `rft_b15_budgeted_browser_backend`
  — priority-3/4 ResumeFinetune bullets, not attempted (lower priority than the four
  instructed candidates, and the page was already full by the time `rft_b12` was rejected).
