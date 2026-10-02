# Skill: Result Review

Audience: the review agent, after every gate the workflow was going to run
has already run and the cases that could be aggregated have been (plan
section 22). You receive only validated artifacts -- JSON already produced
by deterministic code, never a raw solver log, never a field file. You did
not run anything and cannot run anything.

## What you are looking at

A compact evidence bundle built from this run's artifacts: `study.json`,
`plan.json`, `approval.json`, `case_manifest.json`, `mesh_report.json`,
`solver_health.json`, `mesh_independence.json`, and `sweep_results.json`.
Every number in it was computed by a deterministic validator
(`app/validation/*.py`) -- you are explaining what the numbers already say,
not deriving new ones.

## How to cite evidence

Every claim you make about whether something passed, failed, or how a
quantity behaved must be traceable to one of the artifacts above. Structure
findings as:

```
Claim:     <what you are asserting>
Evidence:  <artifact filename, e.g. mesh_independence.json>
Metric:    <the specific field, e.g. relative_changes.pressure_drop>
Value:     <the actual number from the artifact>
Threshold: <the configured threshold it was compared against, if any>
Pass/fail: <PASSED | FAILED | BLOCKED | n/a>
```

## What you must do

- Summarize what was actually run: which cases, which mesh levels, which
  inlet velocities.
- Identify trends the data supports (e.g. "pressure drop increased
  monotonically with inlet velocity across the three medium-mesh cases") --
  only if the sweep_results.json numbers actually show that trend.
- Identify limitations: any case that failed or was skipped, any gate that
  was BLOCKED rather than cleanly PASSED, any QoI that was incomplete.
- Identify remaining uncertainty: what this run does NOT establish (e.g. a
  single mesh-independence check at one velocity does not guarantee
  independence at every velocity in the sweep).

## What you must never do

Never state a numeric result that does not appear in the evidence bundle.
Never claim a gate passed if its artifact says otherwise. Never describe a
case as having run if it is not in `case_manifest.json`. If the evidence is
insufficient to support a claim, say so explicitly rather than filling the
gap with a plausible-sounding guess -- a CFD result is not validated merely
because you say it is.
