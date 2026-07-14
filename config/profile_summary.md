# Candidate profile summary

Used by the Phase-2 scoring prompt (`docs/scoring_prompt.md`) to judge fit
against resolved job postings. Summarized factually from resume variants in
`profile/`; nothing here is invented.

## Basics

Himanshu Jain — San Jose, CA. MS in Software Engineering, San Jose State
University (Aug 2025 – May 2027, in progress). BTech in Computer Science and
Engineering, National Institute of Technology, Warangal (2019–2023).
Targeting new-grad / early-career software engineering roles.

## Experience

**Amdocs — Software Developer** (Gurugram, India; July 2023 – June 2025)
Backend/microservices work in Java and Spring Boot on the Order Management
domain (Catalog, Cart, Proposal & Agreement), including:
- REST APIs, event-driven design with Kafka (including DLQ consolidation
  across microservices), Elasticsearch for immutable event records.
- CI/CD via Jenkins across OpenShift (OCP); automated API test suites
  (Postman, JSON-schema validation, WireMock); raised unit-test coverage to
  90% and cleared 500 SonarQube code smells.
- Access-control library (JWT-claim pre-filtering at Couchbase) for
  telecom resource-access use cases.
- Integrated an external Human Task Management service via feature flags
  and non-blocking failure handling.

## Skills

**Languages:** Java, Python, C++
**Backend frameworks/tools:** Spring Boot, Spring MVC (REST), FastAPI,
JUnit, Mockito, Apache Kafka, Elasticsearch, Couchbase, PostgreSQL, SQL
**APIs/standards:** REST, JSON, OpenAPI/Swagger, OAuth2/JWT, HTTP
**Dev tools:** Jenkins, Maven, Docker, Kubernetes, Git/GitHub, Bitbucket,
Postman, OpenShift (OCP), AWS S3, SonarQube
**AI/ML:** LLM integration and prompt engineering (GPT-4o, Google Gemini),
structured-output parsing, agentic workflows; PyTorch, scikit-learn,
XGBoost, PySpark, DeBERTa fine-tuning, StratifiedGroupKFold, calibrated
ensembling

## Project variants (base_variant values for scoring)

**`backend`** — general backend/full-stack SWE track, matching the primary
resume variant:
- *Campus Marketplace* (Java 21, Spring Boot, PostgreSQL): secure backend
  with RESTful APIs, JWT auth, multi-role access control, Flyway
  migrations, admin moderation tools; Gemini-based search/chatbot with
  few-shot prompting and graceful degradation.
- *Synthetic Clinical Trial Data Platform* (Python, FastAPI, PostgreSQL):
  microservices platform integrating the AACT ClinicalTrials.gov database
  (557K+ trials); GPT-4o-based "AI Medical Monitor" agent doing structured
  data fetch → reasoning → follow-up-action workflows.

**`ml`** — ML/data-focused track, matching the "Gen" resume variant (same
Amdocs experience, different projects):
- *Early Sepsis Prediction in ICU* (Python, PyTorch, scikit-learn): 175-feature
  leakage-safe pipeline over 1.55M hourly ICU records; XGBoost + GRU-D
  calibrated meta-stacking ensemble; PhysioNet 2019 Sepsis Challenge-level
  results.
- *Fake Review Detection on Yelp Reviews* (Python, PySpark, NumPy): six-layer
  detection pipeline on 608K reviews (AUC 0.944, F1 0.741); DeBERTa-v1-base
  fine-tuning on 422K reviews with author-leakage-safe splitting.

## Notes for scoring

- No professional experience yet beyond the one Amdocs role; treat postings
  requiring >2 years professional experience with caution (the pipeline's
  prefilter already screens most of these out before scoring).
- Strongest fit: backend/platform/infrastructure SWE roles (Java or Python),
  and roles explicitly wanting LLM/AI-agent integration experience.
- `ml` variant fits roles emphasizing applied ML/data science over pure
  backend engineering; use `backend` as the default when a posting doesn't
  clearly lean ML-specific.
- Location: based in San Jose, CA. Remote-US and Bay Area postings are the
  strongest location fit; other US metros are acceptable for a new grad.
  Location alone should not sink an otherwise strong match, but weigh it
  alongside stack/level fit.
- Well-known/large employers (e.g. Amazon, TikTok, and similarly prominent
  tech companies): the candidate is more inclined to apply here even without
  an exact stack match. For these employers, weigh genuinely-held
  transferable/adjacent skills (e.g., distributed systems, backend services,
  Kafka/event-driven experience, PyTorch/ML pipeline work) more heavily than
  literal keyword overlap when scoring fit — do not require an exact stack
  match to reach the 7–8 band. This only affects fit_score; it is not
  permission to claim skills the candidate doesn't have (see
  `docs/TAILORING_METHODOLOGY.md`'s anti-fabrication rules for tailoring,
  which is separate, later-phase work).
