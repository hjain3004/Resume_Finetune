"""Offline evaluation harness for Tailor2.

Builds orchestration, schemas, reports, and deterministic tests for later
controlled Top-10 / human-preference evaluations. This package never invokes
a live model provider, mutates `data/jobs.db`, scrapes job sites, or edits
`src/tailor2/**` -- see docs/tailor2_evaluation_harness.md for the full
design and the explicit non-goals.
"""
