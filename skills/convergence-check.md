# Skill: Convergence Check / Diagnosis

Audience: the diagnostic agent, after Gate C (solver health) has already
FAILED deterministically. You are given compact evidence, never the raw
solver log, unless you have no other option (plan section 18).

## What you are looking at

The evidence you receive is a summary already computed by
`app.validation.convergence.check_solver_health`:

- `converged`: did the solver explicitly report meeting its residual
  targets before the run ended?
- `iterations`: how many iterations it took to converge, if it did.
- `last_time`: the last iteration/time value reached, whether or not it
  converged -- this tells you how far the run actually got.
- `residual_trend`: `decreasing`, `stagnant`, `increasing`, or `unknown`,
  computed from the residual history.
- `final_residuals`: the last reported residual per field.
- `fatal_error`: whether OpenFOAM reported a fatal error.
- `reasons`: the specific reasons Gate C failed.

## Diagnosis procedure

1. If `fatal_error` is true or `residual_trend` is `increasing`: the run is
   numerically unstable. Propose `relaxation` -- a **lower** relaxation
   factor than the template default (0.9) to make the next attempt more
   conservative.
2. If `converged` is false but the trend is `decreasing` or `stagnant` and
   there was no fatal error: the run most likely just needed more
   iterations. Propose `time_control` -- a larger `endTime` than
   `last_time`, enough to plausibly reach convergence.
3. If residuals look reasonable but the mesh is known to be non-orthogonal
   (see the mesh quality report, if provided), propose
   `numerical_solver_setting` -- increase `nNonOrthogonalCorrectors` by one
   or two.

## What you may never do

You may propose exactly one action, from exactly one of: `relaxation`,
`numerical_solver_setting`, `time_control`. Nothing else is a valid
`action_type`, no matter how confident you are that some other change (a
different turbulence model, a different mesh, a different boundary
condition) would fix the problem. If none of the three allowed actions
seems likely to help, still propose the best of the three and say so
honestly in `reason` -- a human reviews every failed retry sequence.
