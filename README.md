# agentic-cfd-local

A small, local only agentic CFD demo: OpenFOAM (Docker) + LangGraph +
SQLite checkpointing + AWS Bedrock for planning/review. See
`agentic_cfd_local_demo_plan.md` for the full design and `AGENTS.md` for
the safety/architecture rules every agent in this repo must follow.


## Verify the environment

```bash
uv run python scripts/smoke_test.py
```

This checks, with real commands: the SQLite checkpoint database is
writable, the OpenFOAM image is present, and `blockMesh` / `checkMesh` /
the solver (`foamRun`) all run successfully on a scratch copy of the
benchmark case.


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
