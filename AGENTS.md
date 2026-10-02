# AGENTS.md — Safety & Architecture Rules for agentic-cfd-local

This file is the contract for any agent (human or AI) working in this repository.
Read this before touching code. These rules are not suggestions.

## 1. Purpose

This repository is a **local-only, learning/research demo** of an agentic CFD
workflow. It is not production engineering software. A CFD result must never
be treated as physically validated merely because an LLM says it is correct.

Full design rationale lives in `agentic_cfd_local_demo_plan.md` at the repo
root. This file (`AGENTS.md`) is the condensed, enforceable subset.

## 2. The one rule that matters most

**The LLM never executes arbitrary commands and never calculates validation
metrics.**

```
LLM proposes -> schema validation -> policy validation -> controlled tool
-> deterministic execution -> deterministic validation -> LLM interpretation
```

Never add a tool shaped like `run_shell(anything: str)`. Every tool the LLM
can call must be narrow, named, and validate its own inputs (case id, path,
parameter name, parameter range) before doing anything.

## 3. Filesystem boundaries

The agent (and any tool it calls) may only read/write inside:

```
cfd_cases/      (read-only templates)
runs/<run_id>/  (read-write, created per run)
knowledge/      (read-only)
skills/         (read-only)
data/           (checkpoint database only)
```

Never mount `/var/run/docker.sock` into the agent application. Never give the
agent access to the home directory, SSH keys, git credentials, or `.env`
contents beyond the specific environment variables it needs.

## 4. Secrets

The LLM backend is AWS Bedrock, not Gemini -- a deliberate deviation from
the original plan document's "no AWS services" constraint, made explicitly
by the project owner. Default model: Amazon Nova Pro
(`apac.amazon.nova-pro-v1:0`), a native AWS model billed directly through
the AWS account. Anthropic models on Bedrock were tried first but go
through AWS Marketplace billing, which this account could not reliably
clear (`INVALID_PAYMENT_INSTRUMENT`, intermittently, across every Anthropic
model tried); swap `BEDROCK_MODEL_ID` to retry them once that's resolved --
`app.llm.LLMService` is the only place that needs to change. AWS credentials
come from the ambient AWS credential chain (`aws configure` / SSO / IAM
role) and are never read from or written to `.env`, a checkpoint, an
artifact, or a report. `.env` only holds non-secret config (region, model
id) and is gitignored; only `.env.example` (placeholder values) is
committed.

## 5. Determinism boundary

These are **ordinary Python programs**, never LLM decisions:

- CFD execution (mesh generation, solving)
- Validation gate pass/fail logic and thresholds
- QoI / conservation / mesh-independence calculations
- Filesystem operations and path validation
- Policy checks (is this parameter/action allowed?)

The LLM may: draft a study plan, propose a diagnosis from compact evidence,
write a human-readable review. The LLM may never: invent a tolerance, accept
a failed gate, choose to retry without going through the bounded-retry
policy, or write outside `runs/<run_id>/`.

## 6. Stage-gate states

A stage may emit only one of: `PASSED`, `FAILED`, `BLOCKED`. No vague states
like `probably_ok`. `FAILED` halts automatic progress. `BLOCKED` requires
human approval before continuing.

## 7. Bounded retries

```
max_solver_retries = 2
max_mesh_retries = 1
```

The diagnostic agent may only propose changes from an explicit allowlist
(relaxation settings, numerical solver settings, time/iteration control). It
may never change geometry, boundary conditions, physical model, material
properties, or validation thresholds.

## 8. Human approval

The first study plan requires explicit human approval before any simulation
runs. The agent must not bypass this gate.

## 9. Working method (for whoever extends this repo)

Implement **one milestone at a time** (see plan section 31). For each
milestone: inspect -> plan -> implement -> test -> run a real command ->
inspect real outputs -> fix -> report. Do not claim success without having
executed the relevant command and looked at its output. Do not jump ahead to
agentic/multi-agent behavior before the deterministic runner and validation
layer underneath it are working and tested.

## 10. Benchmark case

The fixed, reproducible benchmark is a 2-D backward-facing-step / separated
flow case (`cfd_cases/backward_facing_step/`), derived from the OpenFOAM
`pitzDaily` tutorial. Baseline inlet velocities: 10, 15, 20 m/s. Mesh levels:
coarse, medium, fine. Do not change the benchmark geometry or operating
points without updating this file and the plan document.
