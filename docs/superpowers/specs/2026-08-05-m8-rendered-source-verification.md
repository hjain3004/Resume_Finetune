# Rendered Source Verification — Proposal

**Date:** 2026-08-05
**Status:** Proposed — awaiting user approval
**Extends:** `2026-08-05-m8-source-verification-design.md`

## 1. The ask

Allow `verify-sources` to render a page with a headless browser before extracting
text, for sources a plain HTTP fetch cannot read.

**This is not a new dependency.** Verified on 2026-08-05:

| Package | Version | Status |
|---|---|---|
| `crawl4ai` | 0.9.0 | already approved (AGENTS.md, M6.5 tier-2 resolver) |
| `playwright` | 1.61.0 | already installed as a hard requirement of `crawl4ai>=1.49.0` |

`src/resolve/browser.py` already drives `crawl4ai` for exactly this purpose in the
ingestion path. The ask is to reuse that capability in the verification path under the
same constraints, not to introduce anything new.

## 2. Justification

From the first `verify-sources` run over 11 bundles, `inconclusive` verdicts split into
two causes:

| Cause | Sources | Renderable? |
|---|---|---|
| Extraction too short — JS-rendered shell | `palantir` x4 (12 chars each), `google/s_about` (281), `notion/careers` (325), `quantcast/s_careers` (287), `amazon/s_careers` (430) | **Yes** |
| HTTP 403 bot wall | `cisco/about` | **No — and must stay No** |

Eight of nine unverifiable sources are pages the site serves willingly but which need
JavaScript to produce text. Those are precisely what a rendering step fixes. They are
currently indistinguishable from fabricated sources, which is the worst property a
verification tool can have: a real page and an invented one both land in the same bucket.

## 3. The bright line

Rendering is permitted to see content a site is **willing** to serve. It is never
permitted to obtain content a site is **refusing** to serve.

- **Permitted:** execute JavaScript, wait for network idle, read `document.body.innerText`.
- **Forbidden:** `playwright-stealth` (present in the tree as a `crawl4ai` dependency, and
  it must remain unused), User-Agent spoofing to impersonate a normal browser, fingerprint
  evasion, CAPTCHA solving, cookie/consent auto-acceptance, or any retry pattern designed
  to work around a 403.

`cisco/about` and the Microsoft hosts must stay `inconclusive`. AGENTS.md prime directive 6
is explicit: if a source resists, mark it failed and surface it — do not escalate tactics.
`src/resolve/browser.py` already states the same rule for the ingestion path; this proposal
inherits it verbatim rather than restating it loosely.

## 4. Determinism

Browser rendering is less reproducible than a plain fetch — timing, lazy loading, A/B
assignment, and locale can all vary the output. Mitigations:

- fixed viewport and locale;
- `wait_until="networkidle"` plus a bounded settle delay;
- the honest verifier User-Agent, unchanged from the plain-fetch path;
- rendering replaces only the **fetch** step; quote comparison stays byte-exact and
  deterministic downstream.

This weakens reproducibility somewhat. The trade is worth it: a `verified` verdict from a
rendered page is far stronger evidence than an `inconclusive` verdict from an unrendered
one, and `inconclusive` is not a pass.

## 5. Scope

- Applies to `scripts/company_bank.py` `verify-sources` only.
- Opt-in via `--render`, defaulting off, so the cheap path stays the default.
- Falls back to the plain-fetch verdict if rendering fails; a render failure never upgrades
  a verdict.
- No change to `src/` data-plane behaviour, `validate-bundle`, `validate-corpus`, or
  `import-corpus`.
- `pytest -q` stays fully offline. Rendering lives in `scripts/`, is never unit-tested
  against the network, and the pure comparison logic in `src/company_bank/verify.py` is
  unchanged.

## 6. Rejected alternative: ScrapeGraphAI

Considered on 2026-08-05 at the user's suggestion and rejected.

It requires an LLM (OpenAI/Groq/Azure/Gemini or local Ollama) and documents no
deterministic extraction mode. Placing a language model in the extraction step would change
the verification assertion from *"the quote appears in text fetched from this URL"* to
*"the quote appears in text a model produced after reading the page."* A model that
paraphrases or fills a gap would break that silently, and unlike the 2026-08-04 fabrication
incident it would not be catchable by re-fetching, because the re-fetch would run the same
non-deterministic extractor.

Its useful component for this project is Playwright, which it installs as a dependency and
which is already present here. `src/resolve/browser.py` reached the same conclusion
independently for the ingestion path: use the browser, refuse the LLM-extraction strategies.

## 7. Non-goals

- Does not resolve bot walls; those stay `inconclusive` by design.
- Does not resolve quote-to-claim fidelity, which remains human review.
- Does not make rendering the default.

## 8. Recommendation

Approve. It reuses an approved dependency already in the tree, converts roughly eight
unverifiable sources into real verdicts, and leaves the etiquette boundary exactly where
`src/resolve/browser.py` already put it. Record the approval in `docs/DECISIONS.md` before
implementation.
