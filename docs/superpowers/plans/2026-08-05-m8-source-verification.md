# M8 Research Source Verification — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:executing-plans if available.
> Steps use checkbox (`- [ ]`) syntax for tracking. Complete tasks in order.

**Goal:** Close the provenance gap that allowed three fabricated research sources to pass
full validation on 2026-08-04. Add an offline snapshot lint and an online re-fetch verifier,
both deterministic, both read-only, neither able to repair a bundle.

**Architecture:** Pure comparison logic in `src/company_bank/verify.py` with the fetcher
injected as a callable. Real network I/O lives only in `scripts/company_bank.py`. Tests
inject a fake fetcher so `pytest -q` never touches the network.

**Tech Stack:** Python 3.11+, `requests`, `trafilatura`, `pytest`. **No new dependencies** —
both libraries are already approved in AGENTS.md and already used in this repository.

**Spec:** `docs/superpowers/specs/2026-08-05-m8-source-verification-design.md`

**Prerequisite:** Company bank foundation is implemented and green
(`python -m scripts.company_bank --help` exposes `validate-bundle`, `validate-corpus`,
`import-corpus`, `lookup`). HEAD is at or after `f0d04b8`.

## Global Constraints

- Do not modify existing validation semantics. `validate-bundle` and `validate-corpus`
  behaviour must be byte-for-byte unchanged; this work is purely additive.
- The verifier is **read-only**. It must never write, edit, delete, or reorder anything
  inside a bundle directory. A test asserts this.
- `pytest -q` must never make a network request. All tests use an injected fake fetcher and
  local fixtures under `tests/fixtures/`.
- Respect AGENTS.md prime directive 6 in the real fetcher: >= 2 s between requests to the
  same host, honest User-Agent, honour `robots.txt`, no auth/CAPTCHA/paywall/bot-wall
  bypass, never fetch LinkedIn member or job-search surfaces.
- No SQLite access, no writes to `config/company_bank/companies/`, no changes to scoring,
  eligibility, sponsorship policy, master profile, or rendering.
- Follow existing code style: type hints everywhere, frozen dataclasses at module
  boundaries, `logging` not `print` inside `src/`, CLI summary output allowed only in
  `scripts/`.

---

### Task 1: Typed model and pure verification core

**Files:**
- Create: `src/company_bank/verify.py`

- [ ] **Step 1: Define the typed model**

Frozen dataclasses and one enum, matching the style of `src/company_bank/model.py`:

```python
class SourceVerdict(str, Enum):
    VERIFIED = "verified"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"

@dataclass(frozen=True)
class FetchResult:
    url: str
    status: int | None      # None when the request never completed
    text: str               # extracted plain text, "" on failure
    error: str | None

@dataclass(frozen=True)
class SourceVerification:
    company_id: str
    source_id: str
    url: str
    verdict: SourceVerdict
    reason: str
    quotes_checked: int
    quotes_found: int

@dataclass(frozen=True)
class BundleVerification:
    company_id: str
    results: tuple[SourceVerification, ...]

@dataclass(frozen=True)
class SnapshotLintFinding:
    company_id: str
    source_id: str
    metric: str
    value: float
    threshold: float
    message: str
```

- [ ] **Step 2: Implement text normalisation**

```python
def normalize_for_match(text: str) -> str
```

Collapse all whitespace runs to a single space and strip. **Do not** case-fold, strip
punctuation, or normalise Unicode quotation marks. A curly-vs-straight apostrophe mismatch
is a genuine mismatch and must surface. Add a test that documents this deliberately.

- [ ] **Step 3: Implement the per-source verdict function**

```python
def classify_source(
    fetch_result: FetchResult,
    quotes: Sequence[str],
    min_text_chars: int = 500,
) -> tuple[SourceVerdict, str, int]
```

Returns `(verdict, reason, quotes_found)`. Rules, in order:

1. `status` is 404 or 410 -> `FAILED`, reason `"page not found (HTTP {status})"`.
2. `status` in {401, 403, 429} or >= 500, or `error` is set, or `status` is None ->
   `INCONCLUSIVE`, reason naming the cause.
3. `status` == 200 and `len(normalize_for_match(text)) < min_text_chars` -> `INCONCLUSIVE`,
   reason `"extraction too short ({n} chars) - likely JS-rendered or bot-walled"`.
4. `status` == 200 and every normalised quote is a substring of the normalised text ->
   `VERIFIED`.
5. Otherwise -> `FAILED`, reason `"{k} of {n} quotes not found on live page"`.

Any other status (e.g. 3xx that the fetcher did not follow) -> `INCONCLUSIVE`.

- [ ] **Step 4: Implement the bundle-level orchestrator**

```python
def verify_bundle_sources(
    bundle: ResearchBundle,
    bundle_dir: Path,
    fetch: Callable[[str], FetchResult],
) -> BundleVerification
```

For each source, gather every `fact.quote` whose `source_id` matches that source, call
`fetch(url)` exactly once per source, and classify. A source with zero citing facts is
`INCONCLUSIVE` with reason `"no facts cite this source"` — it should not exist and is worth
surfacing. The function must not touch the filesystem beyond what it is given, and must not
write anything.

**Verify:** `python -c "import src.company_bank.verify"` succeeds.

---

### Task 2: Offline snapshot lint

**Files:**
- Modify: `src/company_bank/verify.py`

- [ ] **Step 1: Implement quote coverage**

```python
def quote_coverage(snapshot_text: str, quotes: Sequence[str]) -> float
```

Numerator is the summed length of **distinct** quotes citing the source; denominator is
`len(snapshot_text)`. Return `1.0` when the snapshot is empty. De-duplicate quotes before
summing so two facts sharing one quote do not double-count.

- [ ] **Step 2: Implement the lint pass**

```python
def lint_bundle_snapshots(
    bundle: ResearchBundle,
    bundle_dir: Path,
    coverage_threshold: float = 0.6,
) -> tuple[SnapshotLintFinding, ...]
```

Emit a finding when `quote_coverage >= coverage_threshold`, with a message explaining that
the snapshot is mostly quote and carries little surrounding page context, and that the
source should be re-verified against its live URL.

Do **not** add a raw file-size threshold. The design spec's copyright-minimization rule
requires short excerpts, so size would penalise correct behaviour.

- [ ] **Step 3: Confirm calibration against known cases**

Add fixtures reproducing the observed ratios: a fabricated-shape snapshot at ~1.0 coverage
must be flagged; a genuine minimal excerpt at ~0.3 coverage must not.

**Verify:** unit tests in Task 5 cover both directions.

---

### Task 3: Real network fetcher with etiquette

**Files:**
- Modify: `scripts/company_bank.py`

- [ ] **Step 1: Implement a per-host rate-limited fetcher**

Build a small fetcher class in `scripts/company_bank.py` (not in `src/`, because it performs
I/O and is never unit-tested against the network):

- track last-request time per hostname; sleep so consecutive requests to one host are
  >= 2.0 s apart;
- User-Agent identifying the tool honestly, e.g.
  `job-pipeline-source-verifier/0.1 (personal job-search research; contact via repo owner)`;
- timeout 20 s connect/read;
- follow redirects, but if the final host fails the bundle's official-domain boundary check,
  return `INCONCLUSIVE`-triggering data rather than silently accepting an off-domain page;
- one retry only, and only on a connection/timeout error — never on any 4xx;
- refuse outright to fetch any `linkedin.com` host, returning an `error` explaining the
  policy;
- check `robots.txt` for the host and, if the path is disallowed, return an `error` of
  `"blocked by robots.txt"` without fetching.

- [ ] **Step 2: Extract text with the existing path**

Use `trafilatura` to convert HTML to plain text, reusing whatever extraction helper the
repository already applies to fetched pages so verification sees text the same way research
did. Fall back to the raw body only when extraction returns nothing, and note that in the
reason string.

**Verify:** manual smoke only; no automated test performs a real fetch.

---

### Task 4: CLI subcommands

**Files:**
- Modify: `scripts/company_bank.py`

- [ ] **Step 1: Add `lint-snapshots`**

```bash
python -m scripts.company_bank lint-snapshots --inbox data/company_research/inbox
```

Optionally accepts a single `bundle.json` path instead of `--inbox`. Prints one line per
finding plus a summary count. Exit 0 always unless `--strict` is passed, in which case any
finding exits 1. Offline; makes no network request.

- [ ] **Step 2: Add `verify-sources`**

```bash
python -m scripts.company_bank verify-sources --inbox data/company_research/inbox
python -m scripts.company_bank verify-sources data/company_research/inbox/amazon/bundle.json
```

Flags:

- `--json-out PATH` — write the full machine-readable report; the only file the command may
  create, and it must be outside any bundle directory;
- `--strict` — treat `inconclusive` as failure;
- `--delay SECONDS` — per-host delay, default 2.0, floor 2.0 (a lower value is rejected).

Output: a per-source table showing company, source id, verdict, quotes found/checked, and
reason; then a summary line counting each verdict.

Exit codes:

- `0` — every source `verified`
- `1` — at least one `failed`
- `2` — no failures but at least one `inconclusive`, only when `--strict` is passed;
  without `--strict` this case exits `0`. Document this in `--help` and assert it in a test.

- [ ] **Step 3: Never mutate bundles**

Both commands are read-only with respect to `data/company_research/inbox/`. Task 5 asserts
this with a directory-hash comparison before and after.

**Verify:**

```bash
python -m scripts.company_bank --help
```

lists both new subcommands and exits 0.

---

### Task 5: Offline tests

**Files:**
- Create: `tests/company_bank/test_verify.py`
- Create: fixtures under `tests/fixtures/company_bank/verify/`

- [ ] **Step 1: Build a fake fetcher**

A callable returning scripted `FetchResult` objects keyed by URL. No test may import
`requests` or open a socket.

- [ ] **Step 2: Cover the verdict matrix**

One test each: quote present -> `verified`; quote absent from a long extraction -> `failed`;
HTTP 404 -> `failed`; HTTP 403 -> `inconclusive`; near-empty JS shell -> `inconclusive`;
timeout/error -> `inconclusive`; unexpected status -> `inconclusive`; multi-fact source
where one quote is missing -> `failed` with `quotes_found` less than `quotes_checked`;
source with no citing facts -> `inconclusive`.

- [ ] **Step 3: Cover normalisation**

Quote differing only by whitespace runs still matches. Quote differing by a curly vs
straight apostrophe does **not** match, and the test says in a comment that this is
deliberate.

- [ ] **Step 4: Cover the lint**

Coverage `>= 0.6` produces a finding; `~0.3` produces none; duplicate quotes are counted
once; empty snapshot returns `1.0` and is flagged.

- [ ] **Step 5: Cover CLI exit codes and read-only behaviour**

Assert the documented exit-code mapping. Snapshot a recursive hash of a fixture bundle
directory before and after both commands and assert equality.

**Verify:**

```bash
pytest -q
```

is green, and the suite makes no network request.

---

### Task 6: Documentation

**Files:**
- Modify: `docs/superpowers/plans/2026-08-04-m8-company-bank-web-research.md`
- Modify: `docs/superpowers/plans/2026-08-04-m8-company-bank-adoption.md`
- Modify: `docs/DECISIONS.md`

- [ ] **Step 1: Add the gate to the research plan**

In the per-batch checkpoint, require `lint-snapshots` after `validate-bundle`, and record
that per-batch `verify-sources` is recommended. Add the normative rule from section 10 of
the spec: **the per-company figures are targets, not floors**; a company with no publicly
accessible guidance produces a smaller dossier and records the gap; fabricating a source to
satisfy a count is a hard stop.

- [ ] **Step 2: Add the gate to the adoption plan**

Insert `verify-sources --inbox data/company_research/inbox` as a mandatory step immediately
before `import-corpus`, with the rule that import must not proceed while any source is
`failed`, and that `inconclusive` sources require explicit user adjudication.

- [ ] **Step 3: Record the decision**

Append a `docs/DECISIONS.md` entry describing the 2026-08-04 fabrication incident, the
missing snapshot-to-URL link that allowed it, the two-layer remedy, and the
targets-not-floors instruction rule.

---

### Task 7: First run and remediation report

**Files:**
- Read only: all existing bundle directories under `data/company_research/inbox/`
- Create: `data/company_research/inbox/verification_report.json` (ignored working artifact)

- [ ] **Step 1: Lint every existing bundle**

```bash
python -m scripts.company_bank lint-snapshots --inbox data/company_research/inbox
```

- [ ] **Step 2: Verify every existing bundle**

```bash
python -m scripts.company_bank verify-sources \
  --inbox data/company_research/inbox \
  --json-out data/company_research/inbox/verification_report.json
```

This covers **all** bundles completed to date, Batch 1 included. Batch 1 was produced under
the same unverifiable contract and is not exempt.

- [ ] **Step 3: Report, do not repair**

Present per company: source count, verdict counts, and every `failed` or `inconclusive`
source with its reason. Do not edit any bundle. Hand the list to the operator, who decides
per source whether to re-research, re-extract from a browser, or drop it.

Expect `inconclusive` results for hosts that bot-wall plain clients (`www.cisco.com` and
`www.microsoft.com` both returned 403 during Batch 1 and 2 research) and for JS-rendered
careers pages. Those are not accusations; they are sources a plain fetch cannot confirm.

- [ ] **Step 4: Stop**

Do not run `import-corpus`. Do not start any research batch. Report and wait.

---

## Definition of done

- `pytest -q` green with zero network access.
- `lint-snapshots` and `verify-sources` both present in `--help` and behaving per the
  documented exit codes.
- Existing `validate-bundle` / `validate-corpus` behaviour unchanged.
- A verification report exists for every bundle completed to date.
- Research and adoption plans carry the new gates; `DECISIONS.md` records the incident and
  the targets-not-floors rule.
- `git commit` with a `feat(m8): ...` message. Do not push.
