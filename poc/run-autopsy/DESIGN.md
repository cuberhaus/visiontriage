# Run Autopsy — settled decisions (grilling in progress)

Status: design being grilled. Nothing is built yet; do not implement from
this file until the grilling session confirms shared understanding.

Settled in round 1 (2026-10-22):

1. **Separate context.** Run Autopsy is a separate bounded context from
   VisionTriage, with its own `GLOSSARY.md` in this directory. The root
   VisionTriage glossary is untouched; "Experiment" never enters it.
2. **Investigation unit.** Exactly one Target Experiment, optionally
   compared against one Baseline Experiment. An Autopsy investigates one
   pair only (see also Discovery, round 2).
3. **Primary question.** Comparative regression: "why did the Target
   Experiment regress against the Baseline Experiment?" Single-run
   autopsies are a degraded fallback, not the demo path.
4. **Purpose (amended by Pol).** A genuinely useful tool first; the
   portfolio proof is that the tool is useful, not a benchmark costume.
5. **Authority.** Read-only over Experiment Artefacts. The agent writes
   only the Autopsy Report and a proposed, unapplied config patch. It
   never applies a patch, launches training, or modifies artefacts.
6. **Models.** Local-first via LangChain/Ollama (real tool-calling),
   provider swappable by environment, scripted fake in CI.
7. **Claims.** Causal claims are Autopsy Hypotheses, not Findings. Each
   requires an Experiment Artefact citation; a deterministic checker
   drops uncited hypotheses. Outputs: report plus structured hypotheses.

Settled in round 2 (2026-10-22):

8. **Evaluation (Q6).** Layered and real-first: the scored benchmark is
   real Anomalib PatchCore (bottle) Baseline/Target pairs with one seeded
   intervention each, artefacts produced by Anomalib itself. A tiny
   synthetic pair is CI smoke only, never quoted as the result. One hero
   case gets a human-run Confirmatory Experiment. Manual local tier,
   never CI; rides on the MVTec/Anomalib work in issue #6.
9. **Home (Q9).** In this repo under `poc/run-autopsy/`, reusing the
   Anomalib runbook and issue tracker. Split to its own repo only if it
   graduates. No root `GLOSSARY-MAP.md` unless it becomes a product
   context.
10. **First user (Q10, provisional).** Pol's own Anomalib PatchCore
    experiments on MVTec (initially bottle). Other Anomalib models and
    other frameworks are out of scope for the moment.
11. **Inputs (Q11, amended by Pol).** Explicit Target/Baseline paths
    *and* a Discovery mode that surveys a supplied collection of
    Experiments to propose a pair. Mechanism (scope, pairing rule,
    human gate) is open in round 3 — it widens the read boundary from
    Q11's original explicit-pair-only recommendation.
12. **Dataset (Q12).** Optional, explicitly supplied, read-only dataset
    root. Without it, data-related hypotheses are reported as unknown.
13. **Confirmatory Experiments (Q13).** Propose-only in v1: each report
    proposes one per top Hypothesis; a human runs it outside the agent.
    Hypotheses are relabelled confirmed only on a recorded human result.
14. **Usefulness bar (Q14).** Pre-registered before the first scored
    run: top-1 Hypothesis matches the seeded cause in >=3 of 4 real
    cases, citation precision 100% (mechanically checked), hero case
    blind-rated "would act on this without re-reading the raw logs".
    Misses are published, not tuned away against the scored cases.

Open:

- **Discovery (Q11 mechanism).** What a Discovery surveys, how it pairs
  Target with Baseline, and whether a human confirms the pair before
  an Autopsy starts. Round 3.
- **Anomalib artefact layout.** What a real PatchCore run directory
  actually contains. A fact to capture from the issue #6 run, not a
  decision; several round-3 questions wait on it.
- Everything downstream: sub-agent roster, tools, budgets, CLI shape,
  intervention menu, scorer implementation.
