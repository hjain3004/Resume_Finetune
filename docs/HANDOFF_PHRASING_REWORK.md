# HANDOFF — master_profile.yaml phrasing rework

Paste everything below into a fresh session in this repo.

---

You are reworking the resume bullet phrasings in `config/master_profile.yaml` for the
job-pipeline repo at `/Users/himanshu_jain/aero/Resume_Finetune/job-pipeline`.

**Read first:** `CLAUDE.md`, then `docs/TAILORING_METHODOLOGY.md` §2-§4. The docs are
authoritative. Use `.venv/bin/python` and `.venv/bin/pytest`; bare `python3` lacks PyYAML.

## Why this work exists

M10's render bake-off produced the first real PDF from `master_profile.yaml`. The user's
verdict: *"the bullet points are just AI slop... this first draft is extremely low quality."*
They are right. The phrasings were AI-authored during M8 Part B with no lint, no length
budget, and no style reference, and it shows.

## The measured problem — read this before touching anything

Do NOT assume the bullets are too long. They are not. Measurements taken 2026-07-31:

| Source | Bullets | Median chars | Max |
|---|---|---|---|
| `profile/Himanshu_Jain.pdf` (user's real resume) | 11 | 295 | 395 |
| `profile/Himanshu_Jain_cv.pdf` | 13 | 259 | 383 |
| `profile/Himanshu_Jain_Gen.pdf` | 12 | 277 | 395 |
| `master_profile.yaml` backend variant | **29** | ~253 | 336 |

**Bullet length is already correct.** The authored phrasings match the user's real style.
An earlier session claimed they were "2-3.5x too long" by measuring against L4's <=2-line
rule; that was wrong, and the user's interview-tested resume is the authority, not the doc.

**The defect is COUNT and FRAGMENTATION:**
- 29 bullets vs the user's real 11-13. This is why the render overflowed to 2 pages.
- Per entry: internship 8, amdocs 6, peerchat 6, campus_marketplace 5,
  clinical_trial_platform 4. The user's own resume gives ~6 to their main job and 2-3 per
  project.
- `int_b1`/`int_b2`/`int_b3` are all priority 1 and all describe *one* piece of work: b1 is
  the adapter layer, b2 (idempotency) and b3 (the AML gateway) are implementation details of
  b1 promoted to headline bullets. The user flagged exactly this.

## The user's actual bullet style — match it

Study `profile/Himanshu_Resume_New.tex`, `Himanshu_Resume_cv.tex`, and
`Himanshu_Resume_Gen.tex` directly (gitignored, not committed) before writing anything.
Extracted patterns:

- **Opening verbs used:** Architected, Automated, Built, Contributed, Designed, Engineered,
  Fine-tuned, Implemented, Improved, Integrated, Raised, Reduced. Past tense, no gerunds,
  never "Spearheaded"/"Leveraged"/"Passionate".
- **Metric-first when there is one.** Real example:
  `"Reduced production data footprint by 40% and improved active query performance by 25% by
  architecting a Purge & Archive capability across 3 microservices; Implemented REST APIs
  for data lifecycle management, integrated Kafka for event-driven archival..."`
  Outcome and number lead; technique follows via "by ..."; supporting detail follows a
  semicolon.
- **Bold the metric, not the noun.** The template wraps key results in `\textbf{}`.
- **Concrete named technology** in nearly every bullet (Spring Boot, Kafka, OpenShift,
  Elasticsearch, PostgreSQL) - this is what carries ATS keyword weight.
- **One bullet = one accomplishment**, with sub-details folded in after a semicolon rather
  than split into a new bullet.

## Your task

1. **Cut bullet counts to a one-page budget.** Target ~12-14 bullets in
   `base_variants.backend.bullet_order` and similarly for `ml`. Keep the strongest; demote
   the rest by leaving them in the profile but out of `bullet_order` (they remain available
   for the M8 tailor to select per JD - do not delete authored content).
2. **Collapse fragmented bullets.** `int_b1`+`int_b2`+`int_b3` should become one or two
   bullets, not three. Apply the same test everywhere: if two bullets describe one project's
   implementation, they are one bullet with a semicolon.
3. **Rewrite phrasings in the user's voice** using the patterns above. Keep 200-395 chars
   for `medium`. `short` should be a genuine one-line variant (~110-150). `long` optional.
4. **Maximize ATS keyword density honestly** - name the concrete technologies actually used,
   per the bullet's `evidence` field. Never add a technology not in `evidence`.
5. **Add a phrasing lint** to `scripts/validate_profile.py`: fail if `medium` > 400 chars,
   if `short` > 200, or if a phrasing starts with a gerund or a banned word from
   `config/banned_words.txt`. Calibrate to the numbers in the table above, NOT to L4.
6. **Add a page-count check to L7** (`src/render/l7.py`): `ParsedPdf` already knows page
   count; assert <= 1 page. Nothing currently enforces the one-page rule anywhere, which is
   how a 2-page render got through. Add a test.

## Hard constraints

- **Never `git push`.** `origin` is a PUBLIC GitHub repo; `config/master_profile.yaml` holds
  real phone/email/private notes that exist only in unpushed commits. Commit locally only.
- **Never invent a claim.** Every rewritten bullet must stay supported by its existing
  `evidence` field. If a bullet's evidence does not support a sharper claim, keep the weaker
  claim. Fabrication is the one unrecoverable failure here.
- Preserve every `bullet_id`. Ids are the G0 traceability contract and M10's renderer, the
  M8 tailor, and L7 all key off them. Rewrite `phrasings`, never renumber ids.
- Do not touch `claim_type`, `evidence`, `defense`, `interview_risk`, or `metric_ledger`
  except where a rewrite makes an existing entry factually stale - and say so if you do.
- Blocked bullets (`claim_type` in `ownership_unresolved`/`needs_input`) must not enter any
  `bullet_order`.
- Baseline: **785 tests passing**. `.venv/bin/python -m scripts.validate_profile` prints OK
  with 5 projects, 47 bullets (4 blocked), base_variants backend and ml.
- One milestone per session. This is profile content work; do not resume M10's bake-off.

## When done

Re-run the M10 bake-off to see the result on a real page:
`.venv/bin/python -m scripts.render_bakeoff --variant backend --template profile/template.tex`

Then show the user the rendered PDF and the before/after bullet counts. The M10 renderer
decision (bake-off Task 10 Step 4) is **paused** pending this rework - choosing a renderer
based on the old content was judged meaningless. Do not decide it yourself; it is the
user's call on visual acceptability.

## Open context

- `profile/Himanshu_Resume_New.tex:217` has an orphan `\end{itemize}` the user may still
  need to fix in Overleaf.
- `docs/DECISIONS.md` records a known gap: a sixth project ("Performance Modeling for Cloud
  Message Queue Systems", Sep-Dec 2025) exists in `Himanshu_Resume_cv.tex` but not in
  `master_profile.yaml`. Out of scope here unless the user asks.
- `config/profile_summary.md` still duplicates facts `master_profile.yaml` owns. Not urgent.
