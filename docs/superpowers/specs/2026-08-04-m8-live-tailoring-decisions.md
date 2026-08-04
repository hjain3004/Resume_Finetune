# M8 Live Tailoring — Decision Record (brainstorm in progress)

**Date:** 2026-08-04
**Status:** NOT A SPEC. Decisions captured mid-brainstorm; the design document is
not yet written. Do not implement from this file.
**Supersedes (once the design lands):** `docs/superpowers/specs/2026-07-30-m8-tailor-critic-design.md`,
which describes the collapsed single-shot architecture.

Purpose: preserve decisions made during the 2026-08-04 brainstorm before session
context ran out, so a fresh session can resume without re-deriving them.

## Verified starting state

- `src/tailor/wrapper.py` is a **skeleton, not a working prototype**. Line 125
  carries `# Mocking prompt for now`; the prompt is a one-line placeholder that
  dumps the entire master profile as JSON.
- It bypasses `MasterProfile.for_tailoring()` (`src/profile.py:672`), sending
  `evidence`, `defense`, `interview_risk`, and real contact details to the model.
- `_extract_json_from_output` returns `{}` on `JSONDecodeError` — malformed model
  output silently becomes an empty draft.
- It invokes `subprocess.run(["claude", "-p", prompt])`, contradicting AGENTS.md
  and CLAUDE.md, which both state tailoring runs "through explicit file contracts."
- `src/tailor/lint.py` has 8 check functions covering parts of L2/L3/L5/L6. L1 and
  L4 are absent.
- `src/llm_trace.py` exists with `write_trace()`. Any trace work must reuse or
  deliberately extend it, not build a parallel mechanism.
- `src/audit_schema.py:19` `validate()` is a hand-rolled **structural** type
  checker. It cannot express semantic constraints.

**Correction owed:** `docs/ROADMAP.md:101` states "M8 item 3 (tailor and critic) is
implemented." That line was written from a memory record before the code was read,
and is misleading given the mocked prompt. It must be corrected to describe item 3
as a skeleton superseded by this work.

## Decisions

| # | Decision | Notes |
|---|---|---|
| D1 | **Evolve `wrapper.py` in place**; do not build a parallel staged pipeline | User choice. Lower risk than first assumed, since there is no working single-shot behaviour to preserve |
| D2 | **File contracts** for model invocation, per AGENTS.md / CLAUDE.md | Supersedes the direct `claude -p` call. **Open sub-question, see O1** |
| D3 | First increment = **contract/trace foundation + S1** | S1's quote-anchored `must_have` terms feed both L3 keyword bounds and S2's coverage table |
| D4 | **Company context from external research, evidence-anchored** | Every fact must carry `{claim, source_url, retrieved_quote}` |
| D5 | External company research feeds **S0's positioning brief only** | Never S2 selection, never S3 bullet edits. Bounds the blast radius of unverifiable claims |
| D6 | Company research is **cached per company**, TTL'd | Cache key = normalised company name. Company facts go stale in months, not days |
| D7 | **Merge S1 and S0** into one call | S0 consumes S1 directly and emits 2-4 sentences. Role separation (P4/Zheng) governs the *critic*, not two analysis stages |
| D8 | **Never merge S2 and S3** | The deterministic validator sits between them by design; that is what makes selection fabrication-proof |

### Resulting LLM call budget

| Call | Scope | Cached |
|---|---|---|
| Company research | per company | yes, TTL'd |
| S1 + S0 (merged) | per application | no |
| S2 selection | per application | no |
| S3 alignment | per application | no |
| G2 critic | per application, <=2 rounds | no |

4-6 calls per application plus one amortised per company, against 5-7 today with
no company research at all.

## Review corrections to fold in (Codex, 2026-08-04 — independently verified)

1. **I11 traceability.** `docs/SELF_HEALING.md:87` requires every LLM invocation to
   archive under `data/traces/`: full inputs, **full raw output, prompt-file content
   hash, model name, timestamp**, and FAILs if a tailored artifact exists without
   its trace. The originally sketched three files (request.json, prompt.md,
   response.json) satisfy none of the last four. Retries must create new immutable
   attempt directories, never overwrite. Reuse `src/llm_trace.py`.
2. **Semantic validation is mandatory and separate from schema validation.**
   `audit_schema.validate` cannot check that a quote is an exact substring of the
   stored JD — and per methodology §3, "a term without a quote is invalid" is *the*
   anti-hallucination device. S1 needs pure semantic checks proving: every quote is
   an exact JD substring; every term uses the JD's exact surface form; terms
   non-empty and non-duplicated; every populated company_context field carries a
   quote; injection evidence is quoted from the JD; unexpected fields rejected.
3. **Typed contracts at module boundaries.** CLAUDE.md requires dataclasses over
   dicts. Use `S1Request`, `S1Response`, `Requirement`, `CompanyContext`,
   `InjectionFlag` — not `payload: dict`.
   *Refinement adopted:* keep **one shared module** for trace/artifact mechanics,
   which are identical across four specified stages and must satisfy I11 uniformly,
   with typed per-stage contracts on top. Shared plumbing, typed edges.
4. **Separate pure parsing/validation from filesystem I/O**, per CLAUDE.md
   ("parsing separated from I/O so parsers are testable on fixtures").
5. **Disable the legacy path in the same increment.** Leaving `run_tailor` callable
   preserves the full-profile PII bypass, the silent `{}` on malformed JSON, and the
   untraced invocation. Adding a safe S1 path beside it is not sufficient.
6. **S1 schema resolutions (accepted):** `company_context` fields are individually
   nullable, with a quote required for every *populated* field;
   `responsibilities_summary` is a list of `{summary, quote}` entries, not free prose.

## Open questions — must be resolved before the design document is written

- **O1. Manual vs wrapper-invoked.** D2 chose "file contracts," but two readings
  exist: (a) the wrapper builds one self-contained prompt, invokes Claude with tools
  disabled, captures raw stdout, and owns every artifact write — the model never
  touches repo files; or (b) the user runs the prompt by hand and saves the output.
  Both satisfy "the model only ever sees one self-contained prompt," but (a) makes
  I11 raw-output capture trivial while (b) makes it a manual step. **Unresolved.**
- **O2. Company research fetch path.** D4 requires `source_url` + `retrieved_quote`.
  Whether retrieval is a web fetch, a user-pasted snapshot, or a cached artifact is
  undecided — and it determines whether "tests never touch the network" is at risk.
- **O3. Cache location and invalidation.** D6 needs a concrete store (SQLite table
  vs on-disk JSON) and a TTL value.

## Recorded for later — not this increment

- **`for_tailoring()` cannot serve S2.** Its signature is
  `for_tailoring(self, base_variant: str)` — it *takes* the base variant, but
  choosing the variant is S2's job. It also carries identity/contact data and full
  phrasings, and omits the project/tag structure S2 needs for domain affinity. S2
  will need a new privacy-minimised structural selection catalog.
- Remaining sub-milestones after this increment: S2 selection + coverage table +
  validator; S3 alignment + finish G1 (L1, L4 absent); G2 critic + revise loop; G3
  packet + taste capture; CLI + DB status + `applications/{company}-{slug}/`
  archival layout with generated by-date views.

## Next session

Resume the brainstorm at O1. Once O1-O3 are resolved, fold every item above into a
design document at
`docs/superpowers/specs/2026-08-04-m8-live-tailoring-design.md`, then run the spec
self-review and the user review gate before any plan is written.
