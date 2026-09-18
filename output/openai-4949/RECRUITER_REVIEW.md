# Senior Technical Recruiter Review — OpenAI, Software Engineer (Applied Emerging Talent)

Reviewer stance: independent pass, performed after drafting, evaluating the résumé as a
first-time reader at OpenAI would (10-second scan, then a closer read).

## Ten-second positioning
Reading order is Education -> Experience -> Projects -> Skills. Within the first
experience entry (MalyTech, Python/FastAPI/PostgreSQL) the reader already sees production
backend engineering, Python, and a relational database. AI/LLM depth shows up in the
Projects section (ResumeFinetune, Fake Review Detection) and again as the *first* category
in Technical Skills. **Verdict: passes.** All five target signals (backend, Python +
relational DB, AI/LLM, product/end-user orientation, reliability/evaluation discipline) are
visible without hunting, though product/end-user framing is the weakest of the five (see
Evidence Limitations below).

## Credibility
Every metric traces to a `verified` or user-approved `estimated` claim in
`config/master_profile.yaml`, with `~` hedges preserved exactly where the source marks a
figure as estimated (Amdocs' five reconstructed percentages). No claim upgrades a team
effort to sole ownership (Campus Marketplace stays "primary developer on a three-person
team"; the entitlement library stays "co-building"). **Verdict: passes.**

## Technical depth
Bullets name the actual mechanism, not just the outcome: atomic PostgreSQL reservations
with payload hashing (not just "prevented duplicates"), reviewer-disjoint dataset splitting
(not just "trained a model"), three-pass self-consistency with median aggregation (not just
"reduced score variance"). **Verdict: passes.**

## JD relevance
JD asks for: Python + some backend, some relational-database experience, interest in AI/ML,
production/end-user product orientation, and speed in a loosely-defined environment. Python
and PostgreSQL appear in three different entries (MalyTech, ResumeFinetune, Campus
Marketplace) from three different angles (FastAPI microservices, a personal data pipeline,
Flyway-managed schema migrations), which reads as breadth rather than a single résumé line
padded three times. AI/ML is covered by two genuinely different disciplines: LLM
orchestration/evaluation (ResumeFinetune) and applied deep learning (DeBERTa fine-tuning),
which is a stronger signal than either alone. **Verdict: passes, with a noted gap** — see
Evidence Limitations.

## Outcome clarity
Every bullet states an action, the technical mechanism, and a concrete result (a metric, a
verified behavior, or a named capability). None trail off into an implementation
inventory. **Verdict: passes.**

## AI slop
Scanned for filler language: no "leverage," "utilize," "synergy," "cutting-edge,"
"innovative," "seamless," "robust," or "state-of-the-art" anywhere in the document.
**Verdict: passes.**

## Keyword stuffing
Technical Skills lists only terms that are demonstrated by a bullet on *this specific*
résumé version — `scikit-learn` and `XGBoost` were dropped from the source profile's
skills list because the two selected projects (ResumeFinetune, Fake Review Detection) don't
exercise them in the bullets actually shown. **Verdict: passes.**

## Redundancy
No two bullets make the same claim from different angles. "Idempotent" appears once
(MalyTech); "fail-closed" appears once (MalyTech AML gateway). **Verdict: passes.**

## Sentence complexity
Five of eight experience bullets and five of six project bullets render in two lines or
fewer. One exception: the lead MalyTech bullet (anti-corruption layer + Core onboarding
service) renders in three lines because it is the single bullet carrying both halves of
that internship's ownership boundary, and MalyTech is capped at three bullets total —
splitting it would either drop a real accomplishment or exceed the bullet cap. This is a
deliberate trade-off, not an oversight. **Verdict: passes with one accepted exception.**

## Project selection
**ResumeFinetune vs. two-project alternative:** kept — it is the strongest, most
differentiated AI/LLM evidence in the whole profile and is listed first per instruction.
**Fake Review Detection vs. PeerChat:** Fake Review Detection wins. PeerChat demonstrates
distributed-systems/backend engineering, which MalyTech's five asynchronous microservices
already establish more strongly (and more recently). Fake Review Detection adds a *different*
kind of AI/ML evidence — hands-on transformer fine-tuning and evaluation rigor (leakage
audits, ablation-driven claims) — that directly answers the JD's "interest in AI/ML" line
and reinforces the reliability/evaluation-discipline signal PeerChat cannot provide.
**Campus Marketplace:** kept at one bullet — it is the only project entry that puts
PostgreSQL in a classic, JD-named relational-database context (schema migrations via
Flyway), distinct from MalyTech's async-service use of Postgres. **Verdict: the two AI/ML
projects plus one relational-database project is the stronger three-project set for this
JD than any two-project reduction; three projects fit the page without crowding it (see
Visual QA).**

## Skills prioritization
AI and Machine Learning is the first category, using precise demonstrated terms (Agentic
AI, LLM Orchestration, LLM Evaluation, Prompt Engineering, Structured Outputs,
Human-in-the-Loop Systems) instead of the prior résumé's vague "LLM Integration" / "AI
Agent Design." **Verdict: passes.**

## Section balance
Experience (8 bullets across 2 entries) is appropriately the largest section for a
candidate with two real engineering roles; Projects (6 bullets across 3 entries) doesn't
overrun it. **Verdict: passes.**

## Does ResumeFinetune increase interview likelihood?
Yes. It is the only evidence on the page of a candidate who has personally designed,
evaluated, and hardened an LLM-driven system end to end — including the specific failure
mode (run-to-run scoring variance) an interviewer at an AI product company would find
credible and worth probing. It reads as initiative and engineering judgment, not a
class assignment. **Verdict: keep, first position confirmed.**

## Evidence limitations (disclosed, not fixed by invention)
The JD leans further into product/end-user framing ("talk to users," "customer-facing
features," "care deeply about the end user experience") than any bullet on this résumé
states explicitly. The underlying evidence supports an implicit version of this signal —
Himanshu is documented as ResumeFinetune's "product owner" who personally uses the system
to run his own job search, and the human-approval-gate bullet gestures at user trust — but
`master_profile.yaml` contains no bullet phrased in first-person product/UX language, and
inventing one would violate the instruction to draw only from evidence. This is flagged
as a real, disclosed gap rather than patched with unverifiable language.

## Overall verdict
**PASS.** No revision cycle was required beyond the drafting choices documented above.
