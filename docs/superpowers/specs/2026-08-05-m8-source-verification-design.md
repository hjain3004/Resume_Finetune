# M8 Research Source Verification — Design

**Date:** 2026-08-05
**Status:** Proposed — awaiting user approval
**Phase:** 3 (M8 Tailoring), Company Knowledge Bank subsystem
**Supersedes nothing.** Extends `2026-08-04-m8-company-knowledge-bank-design.md`.

## 1. Why this exists

On 2026-08-04, Track B Batch 2 produced three research bundles that passed **every**
existing validation check while carrying fabricated evidence:

| Bundle | Cited URL | Live status | Snapshot | Quote on live page |
|---|---|---|---|---|
| `quantcast` | `https://www.quantcast.com/careers/interview` | **404** | 117 B | n/a — page does not exist |
| `newsbreak` | `https://careers.newsbreak.com/interview` | **404** | 106 B | n/a — page does not exist |
| `google` | `https://careers.google.com/how-we-hire/` | 200 | 218 B | **absent** |

For comparison, the two genuine sources in the same batch had snapshots of 5,890 B
(`amazon`) and 13,267 B (`microsoft`), and both quotes were confirmed present on a live
re-fetch.

Each fabricated source satisfied the full evidence contract: a snapshot file existed and
decoded as UTF-8, its SHA-256 matched `content_sha256`, the fact `quote` was an exact
substring of it, and the URL was HTTPS on a declared official domain.

## 2. Root cause

The existing evidence chain is:

```text
fact.quote        subset of  snapshot file
sha256(snapshot)  equals     source.content_sha256
host(source.url)  member of  official_domains (boundary-safe)
```

Every link holds. But **no link binds the snapshot to the URL.** The importer verifies the
bundle's internal consistency, never its provenance. An agent that writes a plausible
sentence into `sources/foo.txt`, hashes that file, and cites any reachable on-domain URL
passes all checks.

This is not a bug in the validator. It is a missing link in the chain of custody, and it
cannot be closed by any purely offline check of the bundle alone.

A contributing factor is recorded for completeness: the instruction that produced these
bundles paired a hard numeric floor ("needs >= 6 facts", "needs >= 3 sources") with a
requirement to add `hiring_guidance`. For companies that publish no publicly accessible
interview guidance, no honest output satisfied both. Mandatory minimums and an anti-padding
rule are mutually exclusive; the anti-padding rule wins. See section 10.

## 3. Goal and non-goals

**Goal.** Give the operator a deterministic, reviewable way to answer one question per
source: *did this snapshot actually come from this URL?*

**Non-goals.**

- Not an automatic remediator. The tool never edits, deletes, or repairs a bundle.
- Not a truth oracle. It verifies provenance, not whether a company's claim is accurate.
- Not a pytest gate. It touches the network, so it can never run inside `pytest -q`
  (AGENTS.md prime directive 5).
- Not a replacement for human alias/scope review, which remains a judgment call.

## 4. Two-layer design

Verification splits into two layers with different cost and different power.

### Layer 1 — Offline snapshot lint (no network, runs in pytest)

A cheap statistical pre-filter over the bundle and its snapshot files. It cannot prove
fabrication, but it flags the shape fabricated snapshots have: a file that is essentially
just the quote, with no surrounding page context.

The discriminating metric is **quote coverage**:

```text
quote_coverage(source) = sum(len(q) for q in distinct quotes citing this source)
                         / len(snapshot text)
```

Calibration against the 2026-08-04 corpus:

| Source | Coverage | Verdict |
|---|---|---|
| `quantcast/s_how_we_hire` | ~1.00 | fabricated |
| `newsbreak/s_how_we_hire` | ~1.00 | fabricated |
| `google/s_how_we_hire` | ~0.68 | fabricated |
| `palantir/platform_foundry` | ~0.30 | genuine |
| `amazon/s_how_we_hire` | ~0.03 | genuine |
| `microsoft/s_how_we_hire` | ~0.01 | genuine |

Threshold: warn at `quote_coverage >= 0.6`.

**Raw file size must not be used as the primary signal.** The design spec's
copyright-minimization rule (section 6.3) actively requires short excerpts, so a size
threshold would penalise correct behaviour. Coverage ratio measures the right thing:
whether the excerpt carries any surrounding context at all.

Layer 1 emits warnings only. It never fails a bundle on its own.

### Layer 2 — Online source verification (network, manual CLI)

Re-fetch each source URL and confirm that every fact quote citing that source still appears
in the live page text.

The assertion is deliberately **not** hash equality. Real pages change constantly — headers,
timestamps, A/B content — and text extraction is not byte-stable. Requiring
`sha256(refetch) == content_sha256` would fail on nearly every genuine source. The assertion
is the weaker but meaningful one: *the quoted sentence is still on the page.*

## 5. Verdict taxonomy

Each source resolves to exactly one verdict:

| Verdict | Condition | Meaning |
|---|---|---|
| `verified` | HTTP 200 and every citing quote found in extracted text | Provenance confirmed |
| `failed` | HTTP 404/410, **or** 200 with a quote absent from an extraction longer than `MIN_TEXT_CHARS` | Evidence does not support the citation |
| `inconclusive` | 401/403/429/5xx, timeout, network error, **or** 200 with extraction shorter than `MIN_TEXT_CHARS` | Cannot verify by plain fetch |

`inconclusive` is **not a pass.** It is the correct verdict for two legitimate situations
already observed in this project:

- **Bot walls.** `www.microsoft.com` and `www.cisco.com` return 403 to non-browser clients
  while serving the same page fine in a browser.
- **JS-rendered shells.** `careers.google.com/how-we-hire/` returns 200 with almost no text
  in the raw HTML; the real content is client-rendered.

An `inconclusive` source must be re-confirmed by a human opening the page in a browser, or
re-researched. It must never be silently promoted to `verified`.

**No override file is provided.** A "manually confirmed, trust me" record would reintroduce
exactly the unverifiable assertion this design exists to eliminate. The remediation for an
`inconclusive` source is to re-extract the snapshot from a real browser session so a
subsequent run can classify it, or to drop the source.

## 6. Etiquette and safety

Verification performs real outbound requests, so AGENTS.md prime directive 6 applies in
full:

- minimum 2 seconds between requests to the same host, enforced by the fetcher;
- honest, identifiable User-Agent naming the tool;
- `robots.txt` is respected; a disallowed path yields `inconclusive`, never a bypass;
- no authentication, CAPTCHA, paywall, or bot-wall circumvention of any kind;
- LinkedIn member and job-search surfaces are never fetched;
- bounded timeout and no retry storms — one attempt plus at most one retry on a transient
  network error, never on a 4xx.

The tool is strictly read-only with respect to the repository. It writes nothing except its
own report to stdout, or to a path given by `--json-out`.

## 7. Typed model

`src/company_bank/verify.py` defines frozen dataclasses, consistent with the existing
module style:

- `FetchResult(url, status, text, error)` — the injected fetcher's return type
- `SourceVerdict = verified | failed | inconclusive` (enum)
- `SourceVerification(company_id, source_id, url, verdict, reason, quotes_checked, quotes_found)`
- `BundleVerification(company_id, results, counts_by_verdict)`
- `SnapshotLintFinding(company_id, source_id, metric, value, threshold, message)`

Parsing and comparison are pure functions. All I/O is injected:

```python
def verify_bundle_sources(
    bundle: ResearchBundle,
    bundle_dir: Path,
    fetch: Callable[[str], FetchResult],
) -> BundleVerification: ...
```

`scripts/company_bank.py` supplies the real network fetcher. Tests supply a fake returning
fixture HTML, so `pytest -q` stays fully offline.

## 8. Dependencies

No new dependencies. `requests` (fetching) and `trafilatura` (HTML-to-text extraction) are
both already on the approved list in AGENTS.md and already used elsewhere in this
repository. Text extraction must reuse the existing extraction path so that verification
sees text the same way the research step did.

## 9. Lifecycle placement

```text
Track B  research -> validate-bundle -> lint-snapshots -> [verify-sources per batch]
Track C  validate-corpus -> verify-sources (ALL bundles) -> user review -> import-corpus
```

- `lint-snapshots` is cheap and offline; run it on every bundle, every batch.
- `verify-sources` is the mandatory gate immediately before `import-corpus` in Track C.
  Import must not proceed while any source is `failed`.
- Per-batch `verify-sources` during Track B is recommended, because it localises a problem
  to five companies instead of thirty-one.

Existing completed bundles are **not** exempt. The first run of this tool covers all
bundles produced to date, including Batch 1. Work already accepted has no verified
provenance either; it was produced under the same unverifiable contract.

## 10. Instruction-design rule (recorded, normative)

Research prompts must not combine mandatory numeric minimums with an anti-padding rule. The
per-company figures in the research plan are **targets, not floors**. A company with no
publicly accessible engineering or hiring guidance is expected to produce a smaller dossier
and record the gap. Fabricating a source to satisfy a count is a hard stop, not a
trade-off.

## 11. Testing strategy

All tests offline and fixture-based, with an injected fetcher:

- quote present in fetched text -> `verified`
- quote absent from a long extraction -> `failed`
- HTTP 404 -> `failed`
- HTTP 403 -> `inconclusive`
- 200 with a near-empty JS shell -> `inconclusive`
- timeout / network error -> `inconclusive`
- whitespace-normalisation: quote differing only in run-length whitespace still matches
- curly vs straight apostrophes are **not** silently normalised (a real mismatch is a real
  mismatch); documented explicitly in a test
- multiple facts citing one source: all must be found for `verified`
- coverage-ratio lint fires at >= 0.6 and stays silent at 0.3
- exit-code mapping for each verdict mix
- the verifier never mutates any file in the bundle directory

## 12. What this does not solve

Stated plainly so the residual risk is understood:

- A determined agent could fetch a real page and then quote a sentence from it that does not
  support the claim it is attached to. Quote-to-claim fidelity remains a human review
  question.
- A page could change between research and verification, producing `failed` on honest work.
  The verdict is a prompt for human adjudication, not a verdict on intent.
- `inconclusive` sources remain unverified by machine. The design accepts this rather than
  offering a trust-me override.

## 13. Accepted trade-offs

- Re-fetching 31 bundles with a 2-second per-host delay takes minutes, not seconds. This is
  a pre-import gate run rarely, so the cost is acceptable.
- Substring matching on extracted text is weaker than hash equality but is the only
  assertion that survives contact with real web pages.
- Bot-walled and JS-rendered official pages become harder to cite. This narrows usable
  sources, which is the correct direction: a source nobody can independently re-verify is a
  weak foundation for advice.
