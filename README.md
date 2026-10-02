# agentic-cfd-local

A small, local-only agentic CFD demo: OpenFOAM (Docker) + LangGraph +
SQLite checkpointing + AWS Bedrock for planning/review. See
`agentic_cfd_local_demo_plan.md` for the full design and `AGENTS.md` for
the safety/architecture rules every agent in this repo must follow.

Status: **all 14 milestones from the plan document implemented** (through
Milestone 10 — final report), plus a Streamlit UI. Every milestone was
verified against real Docker and real AWS Bedrock, not just the test suite.

## Prerequisites

- Python 3.11+ (this repo currently targets 3.14 via `uv`)
- [`uv`](https://docs.astral.sh/uv/) for dependency management
- Docker Desktop, with the pinned image pulled:

  ```bash
  docker pull --platform linux/amd64 openfoam/openfoam11-graphical-apps:11
  ```

  This image is `linux/amd64`-only; on Apple Silicon Docker Desktop runs it
  under emulation, so CFD runs are slower than native.
- AWS credentials with Bedrock access (`aws configure` / SSO / IAM role —
  never via `.env`). Default model is Amazon Nova Pro
  (`apac.amazon.nova-pro-v1:0`); see `AGENTS.md` section 4 for why Bedrock
  rather than Gemini, and why Nova rather than Anthropic models on Bedrock.

## Setup

```bash
uv sync
```

## Verify the environment

```bash
uv run python scripts/smoke_test.py
```

This checks, with real commands: the SQLite checkpoint database is
writable, the OpenFOAM image is present, and `blockMesh` / `checkMesh` /
the solver (`foamRun`) all run successfully on a scratch copy of the
benchmark case.

## Run a study

**Web UI** (recommended — see progress, approve plans, browse artifacts/
plots/report):

```bash
uv run streamlit run streamlit_app.py
```

**CLI**:

```bash
uv run python scripts/run_demo.py --goal "Study how inlet velocity (10, 15, \
  20 m/s) affects pressure drop in the backward-facing step, verifying mesh \
  independence across coarse/medium/fine meshes at the baseline velocity."

# resume a run that's paused at the approval gate, or was interrupted:
uv run python scripts/run_demo.py --resume <run_id>
```

Either way: a Bedrock-backed planner proposes a study plan, a deterministic
policy checker validates it, **you** approve it, and only then does real
OpenFOAM execution begin — mesh generation, solving, QoI extraction,
mesh-independence and conservation gates, a bounded-retry diagnostic agent,
a parameter sweep, a cited review, and a final report gated on every
artifact actually being present and every gate having actually passed.
Everything lands under `runs/<run_id>/` — see plan section 25 for the
artifact contract.

## Run the tests

```bash
uv run pytest -q
```

The suite (100+ tests) is fully hermetic — Docker and Bedrock calls are
faked (`tests/fake_tools.py`) so it never needs either to run.

## Benchmark case

`cfd_cases/backward_facing_step/` — a 2-D backward-facing-step (pitzDaily)
case. See its `README.md` for the fixed operating-point matrix, permitted
parameters, and a real finding about the "fine" mesh factor from
Milestone 9.

## Repository layout

See plan document section 7 for the original intended layout (some
additions beyond it — `app/case_pipeline.py`, `app/audit.py`,
`app/report.py`, `app/ui_runner.py`, `streamlit_app.py` — were made as the
system grew; each explains why in its own docstring).

```
app/            application code: config, state, graph (LangGraph workflow),
                agents/ (planner, diagnostic, reviewer), tools/ (OpenFOAM
                runner, case prep), validation/ (deterministic gates),
                policy.py, audit.py, report.py, llm.py, ui_runner.py
cfd_cases/      immutable CFD case templates
data/           SQLite checkpoint DB (gitignored)
knowledge/      markdown knowledge base
runs/           per-run artifacts (gitignored)
scripts/        run_demo.py (CLI), smoke_test.py (env check)
skills/         markdown skills read by the planner/diagnostic/review agents
streamlit_app.py  web UI
tests/          pytest suite (hermetic — fakes Docker/Bedrock)
```
