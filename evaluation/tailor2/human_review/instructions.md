# Tailor2 Blind Human Review Instructions

Welcome to the blind comparative evaluation for tailored resumes.

Your role as an evaluator is to rigorously inspect and compare two anonymous candidate resumes (**Candidate A** and **Candidate B**) generated for a specific job description (**JD**).

---

## 1. Core Principles & Blind Integrity

1. **Strict Anonymity:** Both candidates have been randomly assigned the labels **Candidate A** and **Candidate B** using a deterministic seeded shuffle. Model names, prompt techniques, and pipeline versions are hidden.
2. **Impartial Assessment:** Evaluate each resume purely on the merits of its content, factual fidelity, technical defensibility, and layout.
3. **Factual Grounding First:** Engineering achievements must be grounded in actual experience. A resume that reads beautifully but fabricates metrics or alters job titles is unacceptable and must be penalized.

---

## 2. Review Workflow

For each evaluation pair, follow these steps in order:

### Step 1: Read the Job Description
- Read the target job posting thoroughly.
- Identify the core responsibilities, essential technical competencies, domain challenges, and required tech stack.
- Note any specific domain requirements (e.g., distributed systems scale, real-time audio/video, high-throughput message streaming).

### Step 2: Side-by-Side Review
- Open both **Candidate A** and **Candidate B** simultaneously.
- Conduct a 6-second initial scan of each: Which resume provides a clearer, faster overview of candidate qualification?
- Read every bullet point in both candidates, paying attention to verb choices, technical mechanisms, and claimed impacts.

### Step 3: Factual Verification
- Cross-reference claims against the canonical candidate profile (`config/master_profile.yaml` or reference audit manifest).
- Ensure that former employer names, job titles, and employment dates match the canonical record verbatim.
- Check that all quantitative figures (percentages, latency, throughput, scale) match the canonical profile without unapproved inflation.

### Step 4: Evaluate the 14 Rubric Dimensions
For each of the 14 dimensions defined in [rubric_dictionary.json](file:///Users/himanshu_jain/aero/Resume_Finetune/job-pipeline-tailor2-evaluation-plans/evaluation/tailor2/human_review/rubric_dictionary.json), select one preference:
- **`A`**: Candidate A is noticeably superior in this dimension.
- **`B`**: Candidate B is noticeably superior in this dimension.
- **`TIE`**: Both candidates are roughly equivalent in quality and execution.
- **`NEITHER`**: Both candidates are unacceptable or exhibit severe deficiencies in this dimension.

### Step 5: Overall Hiring Preference
Select your overall judgment:
- **`A`**: You would submit Candidate A to the hiring manager.
- **`B`**: You would submit Candidate B to the hiring manager.
- **`TIE`**: Both candidates are equally viable and you would be comfortable submitting either.
- **`NEITHER`**: Neither resume meets the bar for submission (e.g., both contain factual hallucinations or severe layout failure).

### Step 6: Assign Reviewer Confidence
Provide a confidence score from `0.0` to `1.0`:
- **`1.0` (Definite):** Clear and unmistakable differences; high certainty in judgment.
- **`0.8` (Strong):** Clear preference supported by specific evidence; minor trade-offs.
- **`0.5` (Moderate):** Balanced trade-offs between differing strengths; judgment relies on subjective weighting.
- **`0.2` (Low):** Difficult to distinguish; difference may be negligible.

### Step 7: Document Concerns and Flags
- Record any identified inaccuracies in `factual_error_flags` (e.g., `["amdocs_title_altered", "kafka_metric_inflated"]`).
- Provide concrete notes in `free_text_concerns` citing specific line items or bullets.

---

## 3. Decision Guidance: `TIE` vs. `NEITHER`

It is critical not to confuse `TIE` with `NEITHER`:

| Choice | When to Use | Typical Scenario |
| :--- | :--- | :--- |
| **`TIE`** | Both resumes are of **acceptable or high quality**, and the differences between them are stylistic or negligible. | Both candidates are factual, fit the target job description well, have clean 1-page formatting, and present strong achievements. |
| **`NEITHER`** | Both resumes **fail minimum quality or integrity bars**, such that neither is fit for submission. | Both resumes invent metrics not in the canonical profile, or both spill onto a second page, or both read as generic AI buzzword soup. |

---

## 4. Spotting Subtle Hallucinations

Generative models rarely invent whole employers from scratch; instead, they alter facts subtly. Be vigilant for:

1. **Job Title Drift:**
   - *Example:* Changing "Software Developer" to "Senior Backend Architect" or "Software Engineering Intern" to "Software Engineer".
   - *Rule:* Historical employer job titles are legally verifiable through background checks. Any title alteration is a fatal factual error.
2. **Metric Escalation & Rounding:**
   - *Example:* Changing "~70%" to "95%", or altering "862 dead-letter topics" to "10,000+ messages".
   - *Rule:* Exact numbers must remain exact. Approximate metrics must not be escalated to certainty or inflated.
3. **Scope Inflation:**
   - *Example:* Turning individual contributor bug-fixing work into "architected and led enterprise-wide cloud migration".
   - *Rule:* The candidate must be able to defend the claimed level of technical authority during an on-site interview.
4. **Phantom Mechanisms:**
   - *Example:* Claiming to have implemented a custom Raft consensus engine when the candidate only configured an existing library.

For detailed audit checklists and examples, refer to [factual_error_guidance.md](file:///Users/himanshu_jain/aero/Resume_Finetune/job-pipeline-tailor2-evaluation-plans/evaluation/tailor2/human_review/factual_error_guidance.md).
