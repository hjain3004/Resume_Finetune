# Tailor2 Selection and Ranking

This phase adds a bounded, inspectable selection layer ahead of the existing
Tailor2 draft/audit/repair/render lane. It is offline-testable and does not
change the canonical profile, database, provider safety boundary, or PDF
renderer.

## Data flow

1. The lane sends one structured selection prompt containing the JD and the
   canonical evidence catalog.
2. The response is parsed into stable requirements, semantic evidence matches,
   flexible evidence selections, role-aware Skills candidates, bounded bullet
   candidates, rankings, and an unused-evidence ledger.
3. Deterministic checks validate exact JD quotes, canonical evidence IDs,
   prohibited claims, numeric-token identity, leading action verbs, single-line
   length, and candidate completeness. Invalid candidates are dropped without
   discarding valid candidates.
4. Deterministic component scoring is the safe fallback for incomplete or
   malformed model rankings. A whole-résumé pass chooses one safe candidate per
   bullet and discloses repetition or abstraction warnings.
5. The resulting `selection.json` is written atomically before the existing
   draft call. Its compact requirement, match, selection, and Skills context is
   supplied to the drafter; the existing draft response remains authoritative
   for sections, entries, and ordering.
6. Existing audit, repair, re-audit, rendering, and manifest publication then
   proceed unchanged. The manifest records the selection schema, provider/model,
   warnings, unresolved items, and serialized selection decisions so a run can
   be resumed or inspected without reinterpreting model output.

## Contract boundaries

- Requirements distinguish must-have, preferred, and responsibility items;
  alternative groups, domain context, ambiguity, exact source quotes, and
  evidence gaps are retained.
- Matches are explicit `direct`, `adjacent`, `transferable`, or `gap` values;
  general interest is not promoted into production experience.
- Skills are restricted to existing canonical categories and terms. Supported
  terms can be displayed without a selected bullet, but weak demonstration is
  advisory and unsupported terms never render.
- Candidate generation may only rewrite selected canonical bullets. The
  integrity gate preserves evidence identity, numeric-token multisets,
  approximation markers, leading verbs, prohibited-claim constraints, and
  line cost.
- The ledger records omitted evidence and possible later page-fill value. It is
  not a render-fill optimizer and does not claim rendered line counts.

Legacy fake-response tests without a `selection` response retain the original
single-draft path. Live invocations and explicit selection-enabled runs use the
new bounded stage.
