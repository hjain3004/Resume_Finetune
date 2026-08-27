# M6.14 Design — Collision-Safe Posting Identity & Targeted Priority Resolution

**Status:** OFFLINE COMPLETE — LIVE TARGETED SMOKE PENDING (2026-08-27)
**Scope:** Offline deterministic repair for manual inbox collisions, cross-requisition dedup collisions, and fail-closed targeted priority resolution.

---

## 1. Problem Statement & Incident Context

On 2026-08-27, run 22 exposed three deterministic defects in ingestion and resolution:

1. **Manual URL Dedup Collisions:** URL-only inbox jobs defaulted to `company="unknown"`, `title=<hostname>`, and `location=None`. Multiple manual URLs on the same hostname produced identical semantic `dedup_key` values, collapsing distinct URLs (e.g. Revolut or Greenhouse postings) into a single row.
2. **Cross-Requisition Dedup Collisions:** Stored postings (e.g. Roblox requisition `7114754`) collided on semantic company/title/location with new requisitions (e.g. Roblox `8072244`). `insert_discovered()` treated them as the same posting, updating the existing row instead of preserving both requisitions.
3. **Lack of Targeted Resolution:** Resolving urgent manual inbox jobs required running a full `--resolve-only` batch across the entire backlog, with no fail-closed mechanism to target specific `DISCOVERED` job IDs.

---

## 2. Architecture & Pure Identity Contracts

### 2.1 Canonical URL & Manual Dedup Key (`src.models`)
- `canonical_job_url(raw_url: str) -> str`: Normalizes scheme (HTTP/HTTPS only), lowercase hostname, formats IPv6 with brackets `[::1]`, strips default ports (80/443), strips trailing slashes on non-root paths, strips tracking parameters (`utm_*`, `fbclid`, `gclid`), and deterministically sorts remaining parameters while preserving fragments.
- Validates against embedded userinfo (`user:pass@`), control characters, authority whitespace, malformed ports, and sensitive query/fragment parameter keys (`token`, `access_token`, `auth`, `authorization`, `api_key`, `apikey`, `secret`, `signature`, `session`, `sessionid`, `jwt`), raising sanitized `ManualUrlError` without leaking raw input or secrets.
- `manual_url_dedup_key(raw_url: str) -> str`: Computes `sha256("manual-url-v1|" + canonical_url).hexdigest()`.

### 2.2 Stable Posting Identity & Collision Escape Key (`src.models`)
- `stable_posting_identity(raw_url: str) -> str | None`: Extracts conservative ATS/board identifiers:
  - `greenhouse:<id>` from `gh_jid` parameter, `job-boards.greenhouse.io`, `boards.greenhouse.io`, or `careers.roblox.com`
  - `ashby:<org>:<posting_id>` from `jobs.ashbyhq.com` (posting ID must be a valid UUID)
  - `lever:<org>:<posting_id>` from `jobs.lever.co` (posting ID must be a valid UUID; rejects `/search`)
  - `workday:<hostname>:<slug>` from `*.myworkdayjobs.com` (requires `/job/` segment, digit in slug; rejects `/search` and navigation routes)
  - `apple:<id>` from `jobs.apple.com/.../details/<id>`
  - `tiktok:<id>` from `lifeattiktok.com/search/<id>`
  - `revolut:<uuid>` from `revolut.com/.../<uuid>`
- Conflicting signals (e.g. multiple differing `gh_jid` parameters or `gh_jid` disagreeing with board path ID) return `None`.
- `collision_dedup_key(semantic_key: str, posting_identity: str) -> str`: Computes `sha256(f"collision-v1|{semantic_key}|{posting_identity}").hexdigest()`.

---

## 3. Storage & Deduplication Semantics (`src.db`)

1. **Explicit `identity_key`:** If `DiscoveredJob.identity_key` is provided (e.g. from manual inbox), validates format (64-char lowercase hex) and uses it directly as `dedup_key`.
2. **Semantic Conflicts with Differing Posting Identities:** When a semantic `dedup_key` conflicts with an existing row:
   - If both rows have recognized and differing stable posting identities, derives `collision_dedup_key` and inserts/updates a distinct row without mutating the original row.
   - If either row lacks a recognized stable posting identity, retains legacy same-posting conflict handling.
3. **Database Helpers:**
   - `get_by_dedup_key(conn, key)`: Retrieves row by `dedup_key`.
   - `require_rows_by_ids_status(conn, job_ids, status)`: Validates that all IDs exist with expected status and no duplicates, preserving order or failing with `TargetSelectionError`.
   - `rows_by_ids_status(conn, job_ids, status)`: Fetches full job rows for targeted IDs in specified status.
   - `eligibility_rows(conn, status, job_ids=None)`: Scopes pre/post eligibility queries to target IDs when provided.

---

## 4. Manual Inbox & CLI Integration (`src.discover.inbox_manual`, `src.run_ingest`)

1. **Inbox Parser & Atomic Rejection:**
   - Whole lines starting with `#` are comments; fragments on URL lines are preserved.
   - Sensitive parameters or invalid URLs raise `InboxInputError`, aborting all inserts and preserving `inbox/urls.txt` byte-for-byte without leaking secrets.
   - Sets `identity_key = manual_url_dedup_key(canonical_url)`.
   - Returns `InboxResult(new_urls, new_pastes, url_job_ids)`.
   - On successful non-dry ingest with URL rows, prints bounded numeric line: `Inbox job IDs: <id1>, <id2>`.
2. **CLI Flags & Fail-Closed Validation:**
   - `--resolve-job-id ID` (repeatable): Restricts resolution to specified DISCOVERED jobs.
   - Requires `--resolve-only`; mutually exclusive with `--discover-only`, `--source`, `--resolve-limit`, `--dry-run`, `--limit`, and `--snapshot-dir`.
   - Rejects duplicate IDs and validates that all target IDs exist in `DISCOVERED` status before calling `db.start_run()`.
   - Runs pre-resolution and post-resolution eligibility gates scoped strictly to the targeted IDs.
