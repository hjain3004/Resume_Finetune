# M8X-1 — Microsoft SkillOpt Evaluation and Integration Boundary Design

**Date:** 2026-08-24

**Status:** Approved for planning only. **No dependency may be added, cloned,
installed, or executed under this document.** Task 1 (the study) may proceed now;
every later task is blocked on a measured deterministic baseline.

**Phase:** 3 (M8 Tailoring), off the critical path

**Umbrella:** `docs/superpowers/specs/2026-08-24-phase3-parallel-workstreams-design.md`

**Family letter:** `X` marks this as experimental and deliberately off the critical
path, following the `M9F` precedent of a distinct family letter for a bounded
third-party evaluation.

## 1. Repository research first

Before any external research, the repository was searched for existing SkillOpt
material. Result: **two mentions, both exclusions.**
`docs/superpowers/plans/2026-07-23-m8-profile-loader.md` lines 9 and 135 state that
the M8 item-1 plan "does not authorize … SkillOpt integration" and requires "no
SkillOpt dependency or integration". There is no SkillOpt design, no note, no
experiment, and no code anywhere in the repository.

So there is no existing plan to extend or supersede. This is the first SkillOpt
document in the project, and the prior exclusions remain in force until this
milestone's promotion gate is passed.

## 2. Sourced facts about SkillOpt

Everything in this section comes from Microsoft-published material. Anything not in
this section is inference and is labelled as such in §3.

**What it is and what it optimizes.** SkillOpt treats a compact natural-language skill
document as the trainable state of a frozen language agent — it optimizes the
*procedure*, not model weights. Microsoft describes it as the first systematic
controllable text-space optimizer for agent skills.

**The loop.** A forward pass has the frozen target model execute a batch of training
tasks with the current skill, recording trajectories and scores. A backward pass has a
separate optimizer model read those trajectories in reflection minibatches, distilling
patterns to preserve from successes and to correct from failures. The update step
proposes add/delete/replace edits, which are merged, deduplicated, ranked, and clipped
by a "textual learning rate". A candidate skill is adopted **only if it scores strictly
higher than the current skill on a held-out validation split**. Rejected edits enter a
rejected-edit buffer used as negative feedback; a slower epoch-wise meta update
consolidates longer-horizon lessons. Ablations show that removing the rejected-edit
buffer or the meta update significantly degrades performance.

**What it requires.** "Automatic evaluation or a reliable verifier." Environments are
YAML configs in `skillopt/envs/<name>/` packages containing an adapter, a data loader,
a scored rollout helper, and an optional seed skill; `SearchQA` is the reference
example.

**Distribution.** MIT license. Python 3.10+. `pip install skillopt`. Configuration via
a provided `.env.example`. Backends include OpenAI Chat/Azure, Anthropic Claude,
Qwen/MiniMax, and OpenAI-compatible endpoints; execution harnesses include Codex CLI,
Claude Code CLI, and Cursor. v0.1.0 was the initial PyPI release (2026-06-02); v0.2.0
(2026-07-02) added the SkillOpt-Sleep offline self-evolution engine, multi-objective
controls, and plugin integrations for Claude Code, Codex, Copilot, and Devin.

**Reported results.** Across six benchmarks, seven target models, and three execution
harnesses (52 evaluated cells), SkillOpt is reported best or tied in all cells. With
GPT-5.5 in direct chat the six-benchmark average rose from 58.8 to 82.3 (+23.5
absolute). Skills are reported to transfer across model scales, between harnesses, and
to related tasks without further optimization.

**Not disclosed in the material reviewed.** Training/validation split sizes, minimum
dataset guidance, per-run cost or compute characteristics, and any privacy or
data-governance guidance. §3 treats each of these as an open risk, not as an absence
of risk.

Sources: [SkillOpt project page](https://microsoft.github.io/SkillOpt/) ·
[Microsoft Research blog](https://www.microsoft.com/en-us/research/blog/skillopt-agent-skills-as-trainable-parameters/) ·
[Microsoft Research publication](https://www.microsoft.com/en-us/research/publication/skillopt-executive-strategy-for-self-evolving-agent-skills/) ·
[github.com/microsoft/SkillOpt](https://github.com/microsoft/SkillOpt)

## 3. Architectural inference — how it would map onto this project

**Everything below is inference by this planning session, not a Microsoft claim.**

### 3.1 What would be the "skill"

The natural analogues are the protected prompt files: `docs/prompts/tailoring_s1.md`,
`tailoring_s0.md`, `tailoring_s2.md`, `tailoring_s3.md`, and the future
`tailoring_g2.md`. Each is already a single natural-language document that governs one
frozen-model stage, which is structurally exactly what SkillOpt optimizes.

The highest-value single target is **S3**, because it is where wording quality is
decided, and the second is **G2**, because critic sensitivity determines what gets
caught. S1 and S2 are heavily constrained by deterministic validators already, so there
is less headroom.

### 3.2 What would be the "verifier" — and why this is the central risk

This project has an unusually good automatic verifier by SkillOpt's standards: static
G1 pass/fail, the token edit-budget ratio, S1/S2 coverage counts, L7 pass/fail, and
rendered line counts are all deterministic, cheap, and already implemented.

**But that verifier does not measure the thing that matters.** The product question is
"would the user actually send this resume", and that is a human judgement captured only
in `data/feedback/`. Optimizing against the deterministic stack alone would reward a
prompt that reliably produces gate-passing, low-edit-budget, keyword-dense resumes that
a human would not send. This is Goodhart's law with a fast feedback loop attached.

The only honest reward signal is a **composite**: the deterministic gates as a hard
admissibility filter (a draft that fails G1 or L7 scores zero, never partially), and
the human `would_submit` / `visual_quality` / `company_alignment` / `unsupported_claims`
fields from `FeedbackRecord` as the actual objective. That makes labelled human
feedback the binding constraint on the entire track — which is why M8X-1 sits after
M8P-8 and not before it.

### 3.3 Adapter boundary, not invasive coupling

SkillOpt would live entirely outside `src/`:

```
tools/skillopt/                     # gitignored working area
├── .venv/                          # separate virtualenv, never the project venv
├── env_tailoring_s3/               # a SkillOpt env package
│   ├── adapter.py                  # calls the repo's own CLIs as subprocesses
│   ├── data.py                     # loads a frozen labelled split
│   └── score.py                    # composite reward, §3.2
└── runs/                           # trajectories, candidate skills, reports
```

The adapter calls `python -m scripts.tailor_pilot run --job-id ... --only s3` with a
candidate prompt path, reads the resulting artifacts, and computes the reward. It
**never imports `src/`**, never writes into `config/`, `docs/prompts/`, or
`data/jobs.db`, and never edits an approved prompt in place. Candidate prompts are
written to `tools/skillopt/runs/<run>/candidates/`, which is exactly the versioned
proposal-artifact pattern AGENTS.md prime directive 7 already mandates for agentic
control-plane work.

`skillopt` is **never** added to `pyproject.toml`. It is installed, if at all, into
`tools/skillopt/.venv` only, so `pytest -q` never depends on it and the project's
approved-dependency list is unchanged.

### 3.4 Data and privacy

The training data would be job descriptions (third-party text), the user's real resume
bullets, and the user's private feedback about them. Rollouts send that content to
whichever model backend is configured, and trajectories are written to disk.

Rules:

- The adapter reuses the **existing privacy-minimised projections**. The optimizer sees
  what S3 already sees — never `identity`, `education`, `evidence`, `defense`,
  `interview_risk`, `metric_ledger`, `known_gaps`, or raw contact details.
- `tools/skillopt/` is gitignored in its entirety. Trajectories contain resume content
  and JD text and must never reach a public remote.
- The first experiment (§4, phase 3) runs on **synthetic** profile and JD data only, to
  validate the adapter mechanics before any real resume content is used.
- Using real feedback data requires an explicit user decision recorded in
  `docs/DECISIONS.md`, naming the model provider and whether the provider's terms
  permit it. This is the user's data about the user's own career; the decision is
  theirs, not the implementer's.

### 3.5 Model and provider assumptions

SkillOpt needs a target model and a separate optimizer model. Anthropic Claude and the
Claude Code CLI harness are both supported (sourced), which matches this project's
existing `invoke_text_model` boundary — but the reported headline results used GPT-5.5
as both target and optimizer, so **this project's numbers should not be assumed to
match the published ones**. Whatever backend is chosen, the *baseline* must be measured
with the same target model the production pipeline uses, or the comparison is
meaningless.

### 3.6 Reproducibility

Every experiment pins: the SkillOpt version (a specific released version and its commit
SHA, recorded before installation), the target and optimizer model ids, the frozen
train/validation split by job id and record revision, the seed prompt's SHA-256, the
repository commit, and the resulting candidate prompt's SHA-256. Without all six a
result is an anecdote.

### 3.7 Cost

Unknown from published material. Inference: one rollout of the S3 stage is one model
call, and SkillOpt performs many rollouts per epoch plus optimizer calls plus
validation rollouts. A run over 40 training examples with a rollout batch and a
validation split can plausibly reach hundreds of calls per epoch. Therefore the
experiment plan requires an explicit call budget, agreed in advance, enforced by the
adapter, and reported against the M8P-8 baseline cost report.

### 3.8 Overfitting

With three examples, any measured improvement is noise. With thirty split 20/10, one
validation flip moves the score by 10 percentage points. Inference: **do not promote
anything on the strength of 3 or 30 examples.** Thirty is enough to prove the adapter
works and to detect a catastrophic regression; it is not enough to justify replacing a
protected prompt. A promotion decision needs at least 60 labelled applications
(40 train / 20 validation), and even then the gate in §5 requires a human re-review of
the validation set rather than a scalar.

## 4. Phased plan

| Phase | What | Blocked on |
|---|---|---|
| 1 | **Feasibility and compatibility study** — this document plus a written memo answering the §6 questions against the repository's actual contracts. Documentation only. | Nothing. Can proceed now. |
| 2 | **Pin and isolate** — record the exact SkillOpt version and commit SHA, and write the isolated-environment and adapter specification. **Still no install.** | Phase 1 accepted by the user. |
| 3 | **Offline mechanics experiment** — install into `tools/skillopt/.venv`, build the env package, and run one tiny optimization against **synthetic** profile/JD data with a stub target model. Proves the adapter, the reward function, and the budget enforcement work. Produces no promotable prompt. | Phase 2 accepted; explicit user approval to install. |
| 4 | **Baseline measurement** — compute the deterministic baseline from the M8P-8 corpus: gate pass rates, edit-budget distribution, G2 round distribution, cost per application, and the human feedback statistics. This is the number SkillOpt must beat. | M8P-8 complete. |
| 5 | **Baseline-versus-SkillOpt evaluation** — one optimization run on the frozen train split, scored on the held-out validation split with the composite reward, plus a **human re-review** of the validation set's resumes. | Phase 3 and Phase 4 complete; ≥ 60 labelled applications; a recorded provider/data decision. |
| 6 | **Promotion gate** — §5. | Phase 5 complete. |

Phases 1 and 2 are documentation and cost nothing. Phases 3–6 each require explicit
user approval before starting.

## 5. Promotion gate

A SkillOpt-produced prompt may replace a protected prompt **only if every one of these
holds**, each recorded in `docs/DECISIONS.md`:

1. The candidate strictly improves the composite reward on a held-out validation split
   the optimizer never saw.
2. Validation contains at least 20 labelled applications and training at least 40.
3. **Zero** validation drafts contain an `unsupported_claims` entry. Fidelity is not a
   spectrum, exactly as in G2's C1 rule and the M8P-8 acceptance gate.
4. Zero validation drafts fail static G1 or L7.
5. The human re-review of the validation set does not reduce mean `visual_quality` or
   mean `company_alignment` versus baseline.
6. The candidate prompt still contains every structural requirement its stage's parser
   depends on — the response-shape contract, the marker token, and the untrusted-data
   instruction. A prompt that optimizes the reward by weakening the contract is
   rejected outright.
7. The D2 drift discipline is run: G1 and G2 are re-executed on the archived golden
   applications with the candidate prompt, and no previously passing gate fails.
8. The cost per application does not exceed the baseline by more than an agreed factor.
9. The user approves, in writing, with the diff between the approved and candidate
   prompt in front of them.

Promotion mechanics: the candidate is copied into `docs/prompts/` as a single commit
that changes exactly one file. Rollback is `git revert` of that commit. There is no
runtime feature flag, because the prompt path is already a CLI argument
(`--prompt-template`) — the "flag" is which file the operator points at, and the
committed default is the approved one.

## 6. Questions the Phase 1 memo must answer

1. Does SkillOpt's env contract accommodate a **subprocess-based** adapter that shells
   out to this repository's CLIs, or does it assume in-process Python task execution?
2. Can the reward be a **composite with a hard admissibility filter** (deterministic
   gates gate the human score to zero), or does the framework assume a scalar in a
   fixed range?
3. Does the validation gate support a **frozen, externally supplied split**, or does it
   partition data itself?
4. What exactly does a "trajectory" contain, and where is it written? This determines
   the privacy footprint.
5. Does the Claude Code CLI harness invoke `claude` in a way compatible with this
   project's tool-disabled, session-persistence-disabled invocation contract, or would
   adopting it weaken that boundary?
6. What is the minimum viable number of training tasks for one meaningful epoch?
7. What is the observed cost of one epoch at this project's scale?
8. Does v0.2.0's multi-objective control let the human signal and the deterministic
   signal be weighted explicitly rather than summed?

Any question that cannot be answered from published material or from reading the
public repository is recorded as unresolved, not guessed.

## 7. Why SkillOpt is not on the critical path

Three reasons, each sufficient on its own:

1. **There is no baseline yet.** No resume has been produced by this pipeline. An
   optimizer with nothing to improve on and no measurement of the current state cannot
   produce a defensible result.
2. **The reward signal does not exist yet.** The human labels SkillOpt would optimize
   against are created by M8P-7 and M8P-8. Running earlier means optimizing a proxy.
3. **It competes for the scarcest resource.** The binding constraint on this project is
   the user's review attention. Spending it on an optimization experiment before the
   deterministic pipeline has produced a single reviewed resume is the wrong order.

## 8. Explicit non-goals

M8X-1 does not, and no document in this milestone authorises: adding `skillopt` to
`pyproject.toml`; cloning, installing, or executing SkillOpt before Phase 3 approval;
editing any file under `docs/prompts/` or `config/`; importing `src/` from adapter
code; writing to `data/jobs.db`; sending real resume or feedback data to any provider
before a recorded user decision; auto-promoting any prompt; or replacing any
deterministic gate with a learned one. The deterministic gates remain the hard floor
regardless of what any optimizer reports.

## 9. Acceptance criteria

- Phase 1 produces a memo at `docs/superpowers/reports/2026-08-24-skillopt-feasibility.md`
  answering all eight §6 questions or recording them as unresolved, with sourced facts
  and inference clearly separated.
- Phase 2 records the pinned version and commit SHA and specifies the adapter boundary
  without installing anything.
- Phase 3 runs entirely on synthetic data in an isolated virtualenv, enforces a call
  budget, and leaves `pyproject.toml`, `pytest -q`, `config/`, `docs/prompts/`, and
  `data/jobs.db` untouched.
- Phase 4 produces a reproducible baseline report from the M8P-8 corpus.
- Phase 5 reports a comparison with all six reproducibility fields pinned.
- No prompt is promoted without every §5 condition, recorded.
- At every phase: `pytest -q` green without SkillOpt installed; DB SHA-256 unchanged at
  `a9966f4afa4771b61e5b1838c9930e4c64062dc9d85d6fbb49cef17447843ae1`.
