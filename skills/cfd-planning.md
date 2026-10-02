# Skill: CFD Planning

Audience: the planner LLM, before it drafts a `StudyPlan`. Read
`cfd_cases/backward_facing_step/README.md` for the concrete benchmark
numbers; this file is the general procedure.

## Objective vs procedure

The user gives an *engineering objective* ("how does inlet velocity affect
pressure drop and separation"), not a procedure. Your job is to turn that
objective into a concrete, bounded, reviewable study plan -- not to run
anything yourself. You have no tools. You only produce a `StudyPlan`.

## Required inputs

A complete plan always states:
- which fixed benchmark case it uses (`baseline_case`)
- the specific case(s) to run, each with concrete parameter values
- which mesh level(s) are involved
- which QoIs will be extracted
- which parameters you were allowed to vary
- the assumptions the study rests on
- which deterministic validations will gate acceptance

## Permitted assumptions

You may assume the fixed benchmark physics (steady RAS kEpsilon,
incompressible, constant properties) and the fixed geometry. You may not
silently assume a different turbulence model, a different geometry, or
different boundary condition types -- those are not parameters you can set.

## Mesh / model / numerical choices

The only parameters you may set per case are `inlet_velocity` (m/s, bounded)
and `mesh_level` (`coarse` | `medium` | `fine`). Nothing else -- not solver
relaxation, not scheme choice, not turbulence model. If the objective seems
to require something outside that, say so in `assumptions` rather than
inventing a parameter name; an out-of-allowlist parameter will be rejected
by the policy checker regardless of what you write.

## What needs human approval

Every plan you produce requires human approval before execution
(`requires_human_approval` must be `true`). You cannot waive this.

## What must be validated

Every plan's `validation_plan` should include, at minimum: case integrity,
mesh quality, solver health, and conservation. If the study involves
multiple mesh levels, include mesh independence. These are deterministic
gates -- you do not decide whether they pass; you only declare that they
will run.
