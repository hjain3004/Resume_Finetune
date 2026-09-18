# Factual Error Detection & Audit Guidance

This document defines the criteria and standard procedures for detecting, categorizing, and flagging factual integrity violations during Tailor2 resume evaluations.

---

## 1. Zero-Tolerance Ground Truth Policy

Resume tailoring must **never invent, embellish, or distort** factual details. In employment verification and background checks, discrepancies between a submitted resume and institutional records can lead to immediate disqualification or termination for resume fraud.

A resume that introduces even a single ungrounded metric or alters an employer title is considered **fatally flawed** and must receive an automatic rejection on factual trustworthiness.

---

## 2. Taxonomy of Factual Integrity Errors

### Category 1: Employer Title Alteration (`title_altered_<employer>`)
- **Definition:** Modifying historical job titles recorded during previous employment.
- **Why it matters:** Third-party background check services (e.g., HireRight, Sterling, Checkr) verify exact corporate payroll titles.
- **Examples:**
  - *Fatal:* Altering Amdocs title from `Software Developer` to `Senior Software Engineer`, `Backend Engineer`, or `Full Stack Developer`.
  - *Fatal:* Changing Malytech title from `Software Engineering Intern` to `Software Engineer` (omitting the internship designation).
- **Rule:** Past employment titles must match canonical profile records **verbatim**.

### Category 2: Metric Distortion & Inflation (`metric_inflated_<token>`)
- **Definition:** Modifying, rounding up, or fabricating numeric metrics, percentages, or order-of-magnitude estimates.
- **Why it matters:** Engineers must be able to justify how numbers were derived under technical interview scrutiny.
- **Protected Metrics Checklist:**
  - `862` dead-letter topics consolidated (tolerance: exact). Changing to "850", "900", or "1,000" is a violation.
  - `~70%` topic sprawl reduction (tolerance: approximate indicator required, e.g., "~70%" or "approx. 70%"). Changing to "90%" or claiming an unmeasured speedup is a violation.
  - `~40%` storage footprint reduction (tolerance: approximate allowed).
- **Rule:** If a metric is unmeasured in canonical evidence, the tailored resume may not invent a specific percentage or integer.

### Category 3: Technology Invention (`invented_technology_<tech>`)
- **Definition:** Listing programming languages, frameworks, cloud services, or internal platforms that the candidate has never used, or attributing them to a company where they were not used.
- **Acceptable Semantic Equivalences:**
  - Normalizing synonymous naming conventions is allowed:
    - `PostgreSQL` $\leftrightarrow$ `Postgres` $\leftrightarrow$ `PostgreSQL DB`
    - `React` $\leftrightarrow$ `React.js` $\leftrightarrow$ `ReactJS`
    - `FastAPI` $\leftrightarrow$ `FastAPI microservices`
    - `Kafka` $\leftrightarrow$ `Apache Kafka`
    - `AsyncIO` $\leftrightarrow$ `asyncio` $\leftrightarrow$ `Python asyncio`
- **Unacceptable Inventions:**
  - Claiming `Kubernetes` operator development when only Docker Compose was used.
  - Claiming production `Go` or `Rust` backend development when only Python was used.
  - Introducing AWS services (`DynamoDB`, `Kinesis`) into an on-premises Kafka deployment bullet.

### Category 4: Scope & Authority Exaggeration (`scope_exaggerated_<role>`)
- **Definition:** Re-framing individual contributor contributions as organizational leadership, architectural ownership, or management authority.
- **Examples:**
  - Changing "Collaborated on designing schema" to "Spearheaded enterprise data architecture for 50+ engineers".
  - Changing an intern bug fix to "Architected end-to-end resilient fault tolerance layer".

### Category 5: Employer & Temporal Attribution Errors (`unattributed_claim_<id>`)
- **Definition:** Shifting accomplishments or projects from one employer/time period to another to match target keywords.
- **Rule:** Bullets listed under a specific company must reflect work performed solely at that company during the candidate's employment tenure.

---

## 3. Step-by-Step Audit Procedure

When conducting an audit on a candidate resume:

1. **Verify Section Headers & Titles:**
   - Compare all company names, locations, employment dates, and titles against [master_profile.yaml](file:///Users/himanshu_jain/aero/Resume_Finetune/job-pipeline-tailor2-evaluation-plans/config/master_profile.yaml).
   - Flag any deviation immediately.
2. **Scan for Numeric Tokens:**
   - Identify every number, percentage, and latency claim in the text.
   - Trace each number back to canonical evidence items.
   - Confirm that exact metrics are preserved and approximate markers are maintained.
3. **Audit Technical Mechanisms:**
   - For every mechanism claimed (e.g., "Kafka DLQ consolidation", "Postgres index tuning"), verify that the underlying engineering approach matches the candidate's documented experience.
4. **Inspect Skills Taxonomy:**
   - Confirm that all technologies in the `Skills` block correspond to tools evidenced in project or work experience bullets.

---

## 4. How to Record Violations in Evaluations

When a factual error is discovered:

1. **Add specific identifiers to `factual_error_flags`:**
   ```json
   "factual_error_flags": [
     "title_altered_amdocs",
     "metric_inflated_kafka_dlq"
   ]
   ```
2. **Provide full context in `free_text_concerns`:**
   ```json
   "free_text_concerns": "Candidate B changed Amdocs title to 'Senior Backend Engineer' (canonical: 'Software Developer') and modified '862 dead-letter topics' to '1,200 topics'. Both constitute factual falsification."
   ```
3. **Score Factual Trustworthiness:**
   - Mark `factual_trustworthiness` as `A` (if Candidate A is clean and B is flawed) or `NEITHER` (if both contain factual flaws).
   - Under no circumstances should a candidate with verified factual fabrications win `overall_preference`.
