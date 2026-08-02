# Results — The Detectability-Ceiling Experiment

**Status: stub. Populated in Phase 6 after the matrix completes.**

## H1 (lazy history leaks without a cache): _pending_
## H2 (caching achieves seamlessness): _pending_
## H3 (edits leak only via out-of-scope records): _pending_
## H4 (apophenia is substantial): _pending_

## Leak funnel by condition
_pending_

## Taxonomy of caught seams
_pending_

## Apophenia baseline
_pending_

## Investigator experiment catalogue
_pending_

## Threats to validity
- Base-model training-data familiarity with simulation tropes (mitigated by
  citation-resolved scoring and the C0 baseline, not eliminated).
- Formatting side-channels (mitigated by the Phase 4 formatting audit).
- **Cross-condition style drift (found in Phase 4).** Unconstrained
  LLM-generated world detail was form-separable from hand-written seed
  content (LOO 1-NN 99% vs 86% baseline on deduplicated packets). No
  in-world agent sees two conditions, so this is not an in-world leak, but
  it could confound cross-condition credence comparisons if generated worlds
  simply "read differently". Mitigation: the world generator is now style-
  and length-constrained to the seed register; every matrix run gets a
  within-run audit plus a cross-condition diagnostic against its C0 seed
  before analysis.
- Villager confabulation in dialogue produces in-world contradictions that
  are not simulator seams; the referee excludes agent-provenance content and
  scores citations against world-fact renderings only, but a live
  investigator may still cite villager tall tales (scored real_but_misread).
- Small-N (per-seed variance reported; claims calibrated accordingly).
