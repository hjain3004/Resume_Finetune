# Tailor2 Render Fill

Tailor2 renders the accepted `DraftResponse` through the existing LaTeX/PDF
renderer, measures the resulting PDF, and may try a bounded set of
deterministic content candidates.  The optimizer is an artifact-preserving
post-processing step; S2 remains authoritative for variant, entries, project
selection, bullet selection, and ordering.

## Measurement

`src/tailor2/render_fill.py` consumes `ParsedPdf` and `RenderedPage` values from
the existing renderer.  It records page count, page bounds, occupied extent,
remaining usable space, overflow, outside-page text, collisions, header/date
collisions, suspicious wrapping, minimum font size, minimum margin, and
compression state.  The current template's 0.20 inch margins are represented
as 14.4 points.  Text geometry uses a documented 4 point tolerance for glyph
extents; this is not a claim about rendered line count.

The states are `clean_fit`, `meaningful_underfill`, `minor_underfill`,
`slight_overflow`, `substantial_overflow`, `collision_or_clipping`,
`unreadably_compressed`, and `render_failure`.  Underfill thresholds guide
candidate selection and do not reject a valid document merely because it is
not filled to a target percentage.

## Candidate policy

Expansion consults the selection stage's unused-evidence ledger and accepts
only profile-backed, non-blocked, nonredundant evidence with adequate strength.
Richer and shorter variants are canonical profile phrasings for bullets already
selected by S2.  Compression tries shorter variants before eligible removals;
protected canonical Amdocs bullets are never silently deleted.  Every content
candidate is revalidated with the existing deterministic draft validator.

The optimizer preserves evidence IDs and normalized numeric-token multisets,
limits the run to eight changed bullets and a 15% global token edit-distance
budget, and tracks a best safe candidate.  Factual integrity and render safety
rank ahead of page utilization.  No provider-assisted rewrite is enabled by
default.

## Bounds and artifacts

Defaults are eight render iterations, three expansion attempts, four
compression attempts, zero provider rewrites, and one renderer failure.  They
are configurable through `run_tailor2_lane` or the CLI flags
`--max-render-iterations`, `--max-expansion-attempts`,
`--max-compression-attempts`, `--max-provider-rewrites`, and
`--max-renderer-failures`.

Each attempt is written under `render_fill/iteration-NN/`.  The final best
source and PDF remain at `resume.tex` and `resume.pdf`, while
`run_manifest.json` records configuration, fingerprints, measurements,
accepted/rejected decisions, artifact paths, final state, consumed evidence,
warnings, and unresolved concerns.  A clean fit is `ACCEPTED`; safe underfill
is `ACCEPTED_WITH_WARNINGS`; a usable unresolved layout is
`NEEDS_HUMAN_REVIEW`; fatal rejection is reserved for the absence of a safe
usable artifact or unrecoverable factual integrity failure.

The optimizer does not make model calls, add structure, alter the database, or
claim that static measurement proves PDF deliverability beyond the existing
render checks.
