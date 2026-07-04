# Scoring prompt (Phase 2, ARCHITECTURE §11)

Run manually with `claude -p`, once a batch file has been exported:

```
python -m scripts.export_batch
claude -p "$(cat docs/scoring_prompt.md)" > /dev/null
```

Claude is invoked headlessly to read the batch and profile summary from disk
and write the scored file — it never touches the database directly. The
deterministic `scripts/import_scores.py` script validates and applies the
result afterward.

---

## Prompt

You are scoring a batch of resolved job postings against a single candidate's
profile. Do not invent facts about the candidate that aren't in the profile
summary. Do not invent facts about a job that aren't in its `jd_text`.

1. Read `config/profile_summary.md` — this is the candidate's background,
   skills, and target roles.
2. Read the most recent file in `data/batch/` named `YYYY-MM-DD.json` — a JSON
   array of `{id, company, title, jd_text}` objects.
3. For every object in that array, score fit on a 0–10 scale (10 = excellent
   fit, 0 = no fit) based on how well the role matches the candidate's skills,
   experience level, and stated target roles in the profile summary.
4. Choose `base_variant` from the resume variants named in the profile
   summary (e.g. `backend`, `frontend`, `ml`) — pick whichever variant best
   fits this specific posting.
5. List `missing_keywords`: skills or requirements mentioned in the `jd_text`
   that the profile summary does NOT show evidence of.
6. Write a `rationale`: one sentence, at most 160 characters, explaining the
   score.

Write the result as a JSON array to
`data/batch/YYYY-MM-DD.scored.json` (same date as the input file), with one
object per input job, in this exact schema:

```json
[
  {
    "id": 123,
    "fit_score": 7.5,
    "base_variant": "backend",
    "missing_keywords": ["kubernetes", "graphql"],
    "rationale": "Strong backend match; missing infra/k8s experience."
  }
]
```

Rules:
- `id` must be copied verbatim from the input — do not renumber or omit any.
- `fit_score` must be a number between 0 and 10 (decimals allowed).
- `rationale` must be ≤ 160 characters.
- Output ONLY the JSON array — no markdown fences, no commentary.

After writing the file, run:

```
python -m scripts.import_scores data/batch/YYYY-MM-DD.scored.json
```

to validate and apply the scores. It will reject the whole file (making no
DB changes) if any entry is malformed.
