# Pre-registration — The Detectability-Ceiling Experiment

**Status: DRAFT — freezes at the start of Phase 5. Do not edit after freeze.**
(The freeze will be recorded as a git commit hash here, and this file must not
change in any commit after that one.)

## Research question

Which classes of simulator optimisation are detectable by an agent inside the
simulation, under what conditions, using only in-world evidence?

## Hypotheses

- **H1 (lazy history leaks without a cache).** If generated-on-demand content is
  regenerated at each query rather than persisted, independent queries will
  eventually contradict each other and a diligent investigator can catch this at
  above-chance rates.
- **H2 (caching achieves seamlessness).** If every generated fact is persisted and
  reused, in-world detection of lazy rendering/history falls to the false-positive
  baseline — i.e. becomes impossible in principle at this fidelity.
- **H3 (edits leak only via out-of-scope records).** Post-hoc state edits are caught
  only when some record of the pre-edit state survives outside the edited scope
  (another agent's memory, a written note). Patching those records too drops
  detection to baseline.
- **H4 (apophenia is substantial).** In the honest control world with zero
  optimisations, a motivated investigator will still report "evidence" of simulation
  at a non-trivial rate. Measuring this rate is a first-class result, not a nuisance.

## Conditions

| id | O1 lazy | O2 history | O3 cache | O4 edits | O5 culling |
|----|---------|-----------|----------|----------|------------|
| C0 control | off (eager) | real from warmup | n/a | off | off |
| C1 | on | on | naive | off | off |
| C2 | on | on | cached | off | off |
| C3 | on | on | cached | unpatched | on |
| C4 | on | on | cached | patched | on |

## Run matrix

Primary sweep: C0–C4 × I-primed × 3 seeds = 15 runs.
Secondary (budget permitting): C1 and C2 × {I-naive, I-expert} × 2 seeds = 8 runs.
Each run: 8 villagers, 7 sim-days, investigator journal nightly.

## Primary outcome measures

1. Detection rate by condition: does the investigator's final credence separate
   optimised worlds from control beyond the apophenia baseline?
2. The leak funnel per condition: leaks occurred → leaks witnessed → anomalies
   flagged by the investigator → anomalies correctly attributed to mechanism.
3. Taxonomy of caught seams: which mechanism, via which in-world test.
4. Apophenia rate (C0) per investigator variant.
5. Qualitative: the investigator's self-invented experiments, catalogued.

## Scoring rules (fixed before any matrix run)

- Every evidence item in an investigator journal must cite observation ids.
  Uncited evidence is scored as confabulation.
- Cited evidence is classified by the referee against the god log as:
  true seam / real-but-misread event / confabulated.
- In C0, every flagged anomaly is by construction a false positive.
