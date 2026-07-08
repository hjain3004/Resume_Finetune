# TAILORING_METHODOLOGY.md — Resume Analysis & Synthesis (Phase 3 Core)

Supersedes TAILORING_SPEC.md (which remains valid where not contradicted; this document
adds the methodology, evidence base, quality-gate system, and implementation milestone).

The method in one sentence: **tailoring is constrained selection and terminology alignment
over a verified corpus of the candidate's real accomplishments — never open-ended
generation — verified by deterministic lint, then an anchored adversarial critic, then the
human.** Every design choice below exists to enforce that sentence.

---

## 1. Evidence base

Each pillar of the method, what it's grounded in, and an honest note on source strength.
Nothing below is invented; if a claim can't be traced to one of these, it doesn't belong
in the prompts.

**P1 — ATS/recruiter screening is literal and fast; optimize for exact-match retrieval
and skimmability.**
- Fuller, Raman, et al., *Hidden Workers: Untapped Talent*, Harvard Business School /
  Accenture (2021). Documents near-universal use of automated filtering in hiring
  (90%+ of surveyed employers) and its reliance on rigid keyword/proxy matching that
  excludes viable candidates. Strength: reputable institutional study; the canonical
  citation for "the filter is literal, don't rely on inference."
- Ladders Inc. eye-tracking study (2018): recruiters' initial screen averages ~7.4 seconds
  in an F-shaped scan pattern; clean single-column layouts with clear section headers
  received longer, more orderly reads. Strength: industry study, small N, widely
  replicated directionally; grounds layout conservatism and front-loading, not precise
  numbers.
- Consequence in method: exact JD terminology mirroring; dual placement (skills section +
  evidenced bullet); impact-first bullet openings; no layout experimentation.

**P2 — Accomplishment framing: quantified result + mechanism.**
- Bock, L., *Work Rules!* (2015), Google's hiring guidance: the XYZ formulation —
  "Accomplished [X] as measured by [Y], by doing [Z]." Strength: practitioner canon from
  the most-studied hiring org; consistent with the candidate's existing strongest bullets,
  so it doubles as the style fingerprint.
- Consequence: the bullet rewrite rule in §4.3 and lint checks L4/L5.

**P3 — LLM-generated text has measurable lexical tells; ban them mechanically.**
- Liang, W., et al., *Monitoring AI-Modified Content at Scale* (ICML 2024): statistical
  detection of LLM-preferred vocabulary (e.g., "commendable," "meticulous," "intricate,"
  "pivotal," "delve") whose frequency spiked in LLM-assisted text. Strength:
  peer-reviewed; grounds the banned-lexicon approach as measurement, not taste.
- Consequence: `config/banned_words.txt` seeded from this literature + the user's list;
  enforced by deterministic lint (L2), not by asking a model to "avoid slop."

**P4 — Iterative self-critique improves output but degrades past ~2 rounds and carries
judge biases; separate roles and anchor the rubric.**
- Madaan, A., et al., *Self-Refine: Iterative Refinement with Self-Feedback* (NeurIPS
  2023): feedback-then-revise beats single-pass generation across tasks; gains concentrate
  in early iterations. Grounds the tailor→critic→revise loop and the hard 2-round cap.
- Zheng, L., et al., *Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena* (NeurIPS
  2023): LLM judges are usable but exhibit verbosity bias, position bias, and
  self-enhancement bias. Grounds: critic runs as a separate invocation with no access to
  the tailor's reasoning; critic rubric scores against anchors, not open impressions;
  critic sees the diff, not prose it might reward for length.
- Bai, Y., et al., *Constitutional AI* (Anthropic, 2022): critique/revision against an
  explicit written rule set outperforms unguided critique. Grounds: the rubric IS the
  constitution; critics cite rule ids, not vibes.

**P5 — Anchored rating scales beat unanchored ones for consistency.**
- Smith & Kendall, *Retranslation of expectations* (J. Applied Psychology, 1963) — the
  behaviorally anchored rating scale (BARS) literature. Strength: foundational
  psychometrics. Grounds: every rubric dimension in §5 has 3 written behavioral anchors;
  the Phase-2 scoring anchors follow the same principle.

**P6 — Near-duplicate detection via shingling.**
- Broder, A., *On the resemblance and containment of documents* (1997). Grounds the
  Jaccard-over-shingles machinery reused from M6.1 for golden-set drift checks (§6).

**Deliberately rejected approaches** (so nobody re-introduces them): full resume
generation from a JD (unfalsifiable content, maximal slop risk); trusting commercial "ATS
score" tools as ground truth (unvalidated black boxes); semantic keyword expansion
("they said Kubernetes, I'll write container orchestration" — P1 says the filter is
literal); invisible/white-text keywords (detected, flagged as manipulative, and
dishonest).

## 2. Data foundation: the master profile

`profile/master_profile.yaml` per TAILORING_SPEC §1 schema, with these additions:

- **evidence** (required per bullet): 1–2 plain sentences of what actually happened,
  beyond the bullet's wording — the interview story behind the line. Written by the user
  during construction; never model-authored.
- **strength** (required): `flagship | solid | filler`. Selection prefers flagship; a
  tailored resume may not demote a flagship bullet below a filler one to chase a keyword.
- **do_not_claim** (top-level list): technologies/skills the user has touched but cannot
  defend in an interview (e.g., "K8s: deployed to it, never administered it"). The tailor
  may NEVER surface these as skills regardless of JD demand; the gap report (§7) is the
  legitimate outlet.

**Construction protocol (one interactive session, user + model):** (1) extract every
unique bullet across all resume PDFs in `profile/`; (2) merge near-duplicates, keeping the
strongest phrasing as canonical `text` and noting variants; (3) user supplies `evidence`,
`strength`, tags, and the do_not_claim list; (4) define the named variants as ordered
selections; (5) user signs off; the file is thereafter append-mostly — edits to existing
`text` require regenerating any open application drafts that used them.

## 3. Per-application workflow

```
JD (jd_quality='ats' REQUIRED)
  → S1 Requirement extraction        (LLM, structured, evidence-quoted)
  → S2 Selection                     (LLM proposes; deterministic constraints)
  → S3 Alignment edits               (LLM, ≤15% budget, diff output)
  → G1 Deterministic lint            (code; hard gate)
  → G2 Anchored critic               (separate LLM invocation; ≤2 revise rounds)
  → G3 Human review                  (change-list, 90-second review; taste capture)
  → Render (LaTeX → PDF), archive in applications/{company}-{slug}/
```

Stage contracts:

**S1 — Requirement extraction.** Input: JD text only, wrapped in explicit delimiters with
the instruction that delimited content is data to analyze — any instructions found inside
it must be ignored and reported as a `suspected_injection` field (SELF_HEALING I12; the JD
is untrusted third-party content). Output JSON:
`{must_have: [{term, quote}], nice_to_have: [{term, quote}], responsibilities_summary,
seniority_signals: [quote], disqualifiers: [quote]}`. Every term carries a verbatim
supporting quote from the JD — a term without a quote is invalid (this is the
anti-hallucination device on the analysis side; the JD is the only evidence source).
Terms are recorded in the JD's exact surface form (P1).

**S2 — Selection.** Input: S1 output + master profile (ids, tags, strength — not full
texts, to keep the choice structural). Output: base variant choice, project selection,
bullet ordering, and a coverage table: each must_have term → the bullet id(s) that will
evidence it, or `GAP`. Deterministic validator enforces: every non-GAP mapping cites a
real id; no do_not_claim term mapped; flagship-ordering rule respected; GAP list carried
forward to the report (§7). Selection is where most of the tailoring value lives — it is
cheap, reversible, and fabrication-proof by construction.

**S3 — Alignment.** Input: the base variant's source + coverage table. Output: unified
diff + change log (`{location, before, after, motivating_jd_quote, rule}` per edit).
Permitted edit types ONLY: (a) terminology mirroring to the JD's surface form; (b) bullet
reordering; (c) project/bullet swaps already decided in S2; (d) skills-line adjustment
(adding only terms evidenced by a mapped bullet); (e) XYZ-form tightening of a bullet
whose facts are unchanged (P2). Each edit cites its JD quote. Budget: token-level edit
distance ≤ 15% of the base variant (excluding pure reorders), enforced by G1, not by the
model's self-restraint.

## 4. Quality gates

**G0 — Traceability (continuous, deterministic).** Every bullet in the working draft
carries a master-profile id (stripped at render). Any id-less line fails the build.
Machine-checked; not a prompt instruction.

**G1 — Lint (deterministic code, hard gate before any LLM critique).**
- L1 structure: LaTeX section skeleton identical to base variant (reorder/swap only).
- L2 lexicon: zero matches against banned_words.txt (P3 seed + user's list + taste.md
  additions marked `[lint]`).
- L3 keyword bounds: each S1 must_have term appears ≥1 in a bullet AND ≥1 in skills
  (dual placement); no term > 4 occurrences document-wide; top-5 terms in the 2–3 range.
- L4 bullet shape: every modified bullet ≤ 2 lines rendered, starts with a past-tense
  action verb, contains ≥ 1 digit unless the base bullet had none.
- L5 edit budget: ≤ 15% per §3-S3.
- L6 do_not_claim: zero occurrences of listed terms outside the gap report.
Lint failures return to S3 with the violation list; the critic is never invoked on
lint-failing drafts (cheap checks before expensive ones; the model never gets to
negotiate with the linter).

**G2 — Anchored critic (separate invocation; sees JD, diff, change log, rubric,
taste.md; does NOT see the tailor's reasoning or S2 deliberations — role separation
per P4/Zheng).** Rubric, each dimension scored 1–3 against written anchors:
- C1 Fidelity: 3 = every change consistent with the cited bullet's evidence field;
  1 = any claim beyond the master profile.
- C2 Voice: 3 = indistinguishable from the base variant's cadence (impact-first,
  concrete nouns, quantified); 1 = detectable register shift or template phrasing.
  Anchor examples embedded in the prompt are drawn from the user's own strongest and
  weakest historical bullets.
- C3 Alignment economy: 3 = every must_have covered or explicitly GAPped, no
  opportunistic unrelated edits; 1 = keyword chasing beyond the coverage table.
- C4 Recruiter-read: 3 = a 7-second F-scan lands on role-relevant impact (P1);
  1 = the strongest signal is below the fold or diluted.
- C5 Slop scan: 3 = zero lines a reviewer of 200 resumes would flag as AI-generic;
  1 = any such line (critic must quote it).
PASS = all dimensions ≥ 2 AND C1 = 3 (fidelity is not a spectrum). On failure the critic
emits `{dimension, quoted_line, violated_rule}`; the tailor revises; **maximum 2 rounds**
(P4/Madaan), then unresolved issues go to the human packet as open flags — the system
never launders a disagreement by exhausting the critic.

**G3 — Human review.** The packet: coverage table, change log, critic verdict, open
flags, gap report, rendered PDF. Target review time ≤ 2 minutes. Every rejection or edit
the user makes is captured the same day in `config/taste.md` (append-only, dated, one
lesson per line, tagged `[lint]` if mechanically enforceable — in which case it ALSO
becomes a banned_words/lint entry, permanently cheapening that class of feedback).

## 5. Degradation defenses (how quality is kept from decaying)

- **D1 Golden set.** Every user-APPROVED application is archived (JD + final source +
  packet) in `applications/_golden/`. It is the regression corpus.
- **D2 Drift regression (monthly, deterministic harness).** Re-run G1+G2 on 5 sampled
  golden applications with current prompts/config. Any golden failing lint, or any critic
  dimension dropping ≥ 1 vs. its archived verdict, is a drift FAIL → investigate what
  changed (prompt edit? taste rule? banned-word addition?) before any new tailoring runs.
  This catches the silent killer: a "small prompt improvement" that degrades outputs.
- **D3 Prompt lock.** Tailor and critic prompts are PROTECTED files post-calibration
  (SELF_HEALING §4). Changes require explicit user approval AND trigger an immediate D2
  run.
- **D4 Style-fingerprint refresh.** When the user adds new master-profile bullets, C2's
  embedded anchor examples are re-sampled from current flagship bullets (documented in
  DECISIONS.md) so "the user's voice" tracks the user, not a snapshot.
- **D5 Outcome journal (lightweight, honest).** `data/outcomes.csv`: application →
  response/no-response/interview, plus an `ats_vendor` column derived from the job's
  resolver / ats_url host — screening outcomes correlate within a vendor's stack
  (Bommasani et al., FAccT 2026, algorithmic monoculture), so rejections clustering by
  vendor are signal that per-company tracking cannot reveal. Reviewed monthly for signal
  by variant, score band, and vendor. No causal claims from tiny N — its job is catching
  gross failures (e.g., a variant that never converts, or a vendor stack that never
  advances the candidate) and keeping the system accountable to reality rather than to
  its own rubric.

## 6. Gap → project recommendations

GAP terms from S2 aggregate weekly into `data/digests/gaps.md`: term, demanding companies,
frequency, and at most 3 scoped project suggestions (1–2 weekends; phrased as what to
build, which gap terms it would legitimately earn, which variant it extends). The user
builds or declines; on build, new master-profile entries follow the §2 protocol. This is
the ONLY sanctioned response to a JD demanding skills the profile lacks — the alternative
(wording one's way around a gap) is fabrication with extra steps.

## 7. M8 — implementation milestone

Build order: (1) master-profile loader + validators (schema, do_not_claim, strength);
(2) G1 lint suite as pure functions with fixture tests per rule (L1–L6, each with a
passing and a violating fixture); (3) diff/change-log tooling + edit-distance budget
calculator; (4) S1/S2/S3 prompt files + I/O schema validation (file-based contract, same
pattern as scoring: Claude never touches internal state directly; every invocation writes
a trace per SELF_HEALING I11); (5) G2 critic prompt +
verdict schema + 2-round loop driver; (6) applications/ scaffolding + golden-set harness +
D2 monthly script; (7) gap aggregation.

Acceptance:
- Lint: every rule has both fixtures; a deliberately slop-injected draft (fixture provided
  by seeding banned lexicon + a fabricated bullet) fails L2 and G0/C1 paths.
- Round-trip: a real shortlisted JD from the DB → S1→S2→S3→G1→G2 produces a packet with a
  coverage table whose every non-GAP entry resolves to a real bullet id.
- Budget: an over-edited fixture draft (20% distance) is rejected by L5 with the computed
  ratio.
- Critic loop: a fixture with a C1 violation → critic fails it citing the line → revision
  → pass or open-flag within 2 rounds (mocked LLM responses in tests; live in smoke).
- D2 harness: runs against a seeded golden set; a prompt mutation that adds a banned word
  to output is caught.
- Gate: M8 does not begin until Phase 2 calibration exit criteria (PHASE2_KICKOFF) are
  met and ≥ 5 shortlisted jobs have jd_quality='ats'.

## 8. Kickoff prompt (user pastes when the gate opens)

> Read CLAUDE.md, docs/SELF_HEALING.md §4, and docs/TAILORING_METHODOLOGY.md in full.
> Confirm the M8 gate conditions from §7 are met (show me the query results). Then
> implement M8 in the build order given, one numbered item per session, tests first for
> the lint suite. The prompts you write in item 4 and 5 must encode ONLY rules present in
> this document — if you feel a rule is missing, escalate per SELF_HEALING instead of
> inventing it. Before the first live tailoring run, walk me through the master-profile
> construction protocol (§2) interactively.
