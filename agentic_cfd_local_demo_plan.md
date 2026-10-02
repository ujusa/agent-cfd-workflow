# Agentic CFD Scientist — Local-Only Working Demo Plan

## 0. Goal

Build a **small but trustworthy agentic CFD workflow** that runs on a developer laptop and demonstrates the core ideas from:

- AWS: *Accelerating CFD development from years to weeks with agentic AI and AWS*.
- `csml-rpi/AI-CFD-Scientist`.
- The Exeter/OIPT-style problem: AI-assisted CFD workflow creation, execution, monitoring, validation, and explanation.

The first version must be:

- **Local for all compute and data**: OpenFOAM, Python, LangGraph, SQLite, files, plots, and validation run locally.
- **Google Gemini for the LLM** via API. This is the one intentional external dependency.
- **No AWS services**.
- **No autonomous physics-changing behavior in v1**.
- **Checkpointed and resumable** using LangGraph + SQLite.
- **Auditable**: every important agent decision and tool execution is recorded.
- **Deterministic where possible**: CFD execution, validation formulas, filesystem operations, and gates are ordinary Python programs rather than LLM decisions.
- **Small enough to finish and run end-to-end** before adding advanced agents.

> Important: this project is a learning/research demo, not production engineering software. A CFD result must never be treated as physically validated merely because an LLM says it is correct.

---

# 1. What We Are Building

The end-to-end demo will look like this:

```text
                    USER
                     |
                     | engineering objective
                     v
             +-------------------+
             |  LangGraph Agent  |
             |     Planner       |
             +---------+---------+
                       |
              +--------+---------+
              |                  |
              v                  v
        CFD Knowledge       Workflow Rules
          / Skills           / Policies
              |                  |
              +--------+---------+
                       |
                       v
             +-------------------+
             | Case Preparation  |
             +---------+---------+
                       |
                       v
             +-------------------+
             | OpenFOAM Runner   |
             +---------+---------+
                       |
                       v
             +-------------------+
             | Run Monitor       |
             +---------+---------+
                       |
                 success/fail
                       |
                       v
             +-------------------+
             | Deterministic     |
             | Validation Gates  |
             +---------+---------+
                       |
             +---------+---------+
             |                   |
             v                   v
      mesh/physics valid       invalid
             |                   |
             v                   v
        Post-process       Diagnostic Agent
             |                   |
             +---------+---------+
                       |
                       v
             +-------------------+
             | Results + Report  |
             +-------------------+
```

The first demo should answer this question:

> **Can an AI agent take a constrained CFD objective, prepare and run a known OpenFOAM case, monitor it, perform objective validation, and produce an auditable result that can be resumed from SQLite?**

---

# 2. Why This Design

The reference `AI-CFD-Scientist` repository is useful as an architectural reference because it separates the study into explicit stages, uses artifacts/contracts between stages, performs a mandatory mesh-independence gate, runs CFD through a controlled case runner, interprets results, and uses stage-gate auditing. It also supports LangGraph orchestration and an interactive skill-driven approach. Do **not** copy its entire codebase into v1; reproduce the architectural ideas in a much smaller project first.

Useful patterns to borrow conceptually:

```text
Stage gates
Artifact contracts
Case isolation
Human approval gates
Mesh independence
Diagnostics before acceptance
Controlled filesystem access
Resumability
Deterministic verification
```

The reference repository uses SQLite for interactive checkpointing, and this project will also use SQLite for the first local demo. This keeps the setup simple and removes the need for a database container. PostgreSQL can be introduced later if the workflow needs multi-process or production-style persistence.

---

# 3. Scope of Version 1

## Included

1. User gives an engineering goal.
2. Planner produces a structured CFD study plan.
3. A CFD policy checker verifies the plan against allowed choices.
4. A known OpenFOAM baseline case is copied into a run directory.
5. The agent can adjust only explicitly permitted numerical parameters.
6. OpenFOAM is executed locally through a controlled runner.
7. Solver output is monitored and persisted.
8. Deterministic checks calculate convergence/health metrics.
9. A mesh refinement experiment is executed.
10. Mesh independence is assessed with a deterministic calculation.
11. Post-processing extracts a small set of quantities of interest (QoIs).
12. A review agent explains the result using collected evidence.
13. All stage outputs are written as JSON artifacts.
14. LangGraph checkpoints the workflow to SQLite.
15. The run can be interrupted and resumed.
16. A final Markdown report is generated.

## Explicitly NOT included in v1

- Automatic modification of OpenFOAM source code.
- Automatic selection among dozens of turbulence/chemistry/plasma models.
- Automatic geometry generation from arbitrary CAD.
- Fully autonomous optimization.
- Arbitrary shell access for the LLM.
- Production HPC scheduling.
- Internet/web search during CFD execution.
- Automatic acceptance of a scientifically questionable result.
- Plasma chemistry in the first case.

These are later phases.

---

# 4. Running Example

## CFD problem

Use a **steady backward-facing-step / separated-flow case** derived from a stable OpenFOAM tutorial-style case, or a small project-local benchmark case built with `blockMesh`.

The first practical target should be:

> **Study how a controlled change in inlet velocity affects the separated flow and pressure drop in a 2-D backward-facing step.**

The exact geometry and operating points must be fixed in the repository so that the example is reproducible.

### Why this case

It is more representative of an industrial CFD workflow than a toy algebraic example, but still small enough to run locally.

It also naturally supports:

- mesh refinement,
- convergence checks,
- pressure-drop calculation,
- recirculation/separation diagnostics,
- parameter sweeps,
- comparison between cases.

## First benchmark matrix

Start with only three cases:

```text
baseline: inletVelocity = 10 m/s
case_02:  inletVelocity = 15 m/s
case_03:  inletVelocity = 20 m/s
```

Then use three mesh levels for the baseline:

```text
coarse
medium
fine
```

Do not start with a large sweep.

---

# 5. Local Technology Stack

```text
Python 3.11+
LangGraph
LangChain core integrations as needed
Google Gemini API
SQLite
langgraph-checkpoint-sqlite
OpenFOAM 11 in Docker
PyVista
NumPy
Pandas
Matplotlib
Pydantic
Typer or argparse
pytest
Docker Compose
```

## Suggested project tooling

Prefer `uv` for Python environment/package management if available.

Alternative: normal `venv` + `pip`.

---

# 6. Local Architecture

## Processes

```text
Host machine
|
+-- Python agent application
|     |
|     +-- LangGraph
|     +-- Gemini API client
|     +-- workflow code
|     +-- validation code
|     +-- report generation
|
+-- SQLite database file
|     |
|     +-- LangGraph checkpoints
|     +-- optional run metadata
|
+-- OpenFOAM container
|     |
|     +-- case files mounted from project/runs
|     +-- blockMesh
|     +-- solver
|     +-- post-processing utilities
|
+-- Local filesystem
      |
      +-- immutable templates
      +-- run artifacts
      +-- logs
      +-- plots
      +-- reports
```

## Data ownership rule

The filesystem is the source of truth for CFD artifacts.

SQLite is the source of truth for **workflow state/checkpoints**.

Do not put large CFD fields into SQLite in v1; keep CFD fields and plots as files/artifacts.

---

# 7. Repository Layout

Create this exact structure initially:

```text
agentic-cfd-local/
|
+-- README.md
+-- AGENTS.md
+-- pyproject.toml
+-- .env.example
+-- .gitignore
+-- docker-compose.yml
|
+-- app/
|   +-- __init__.py
|   +-- config.py
|   +-- state.py
|   +-- graph.py
|   +-- llm.py
|   |
|   +-- agents/
|   |   +-- planner.py
|   |   +-- reviewer.py
|   |
|   +-- tools/
|   |   +-- case_tools.py
|   |   +-- openfoam_tools.py
|   |   +-- monitoring_tools.py
|   |   +-- validation_tools.py
|   |   +-- artifact_tools.py
|   |
|   +-- validation/
|   |   +-- convergence.py
|   |   +-- mesh_independence.py
|   |   +-- conservation.py
|   |   +-- qoi.py
|   |
|   +-- prompts/
|       +-- planner.md
|       +-- reviewer.md
|
+-- skills/
|   +-- cfd-planning.md
|   +-- openfoam-run.md
|   +-- convergence-check.md
|   +-- mesh-independence.md
|   +-- result-review.md
|
+-- cfd_cases/
|   +-- backward_facing_step/
|       +-- README.md
|       +-- template/
|           +-- 0/
|           +-- constant/
|           +-- system/
|           +-- scripts/
|
+-- knowledge/
|   +-- cfd_basics.md
|   +-- openfoam_workflow.md
|   +-- validation_rules.md
|   +-- case_notes.md
|
+-- runs/
|   +-- .gitkeep
|
+-- tests/
|   +-- test_validation.py
|   +-- test_case_safety.py
|   +-- test_workflow.py
|   +-- test_checkpointing.py
|
+-- scripts/
    +-- db_init.py
    +-- smoke_test.py
    +-- run_demo.py
```

---

# 8. Core Design Principle: LLM Does Not Execute Arbitrary CFD Commands

Never give the LLM a generic tool like:

```python
run_shell("<anything>")
```

Instead expose narrow tools:

```python
prepare_case(case_id, parameters)
run_mesh(case_id)
check_mesh(case_id)
run_solver(case_id)
read_solver_log(case_id)
extract_qoi(case_id)
run_validation(case_id)
compare_cases(case_ids)
```

Each tool must validate:

- case ID,
- path is under allowed run directory,
- parameter names are allowed,
- numeric values are within configured ranges,
- no writes happen outside the run directory,
- expected executable is being invoked.

This is one of the most important reliability requirements in the entire project.

---

# 9. State Model

Use a Pydantic model or TypedDict compatible with LangGraph.

The state should contain at least:

```text
run_id
user_goal
study_plan
approval_status
case_specs
current_case_id
current_stage
mesh_results
solver_results
validation_results
qoi_results
diagnostics
agent_decisions
artifacts
errors
retry_count
final_report_path
```

Every case should also have a deterministic record:

```json
{
  "case_id": "case_001",
  "parameters": {
    "inlet_velocity": 10.0
  },
  "mesh_level": "medium",
  "status": "completed",
  "solver": "...",
  "start_time": "...",
  "end_time": "...",
  "return_code": 0,
  "residual_status": "passed",
  "validation_status": "passed"
}
```

---

# 10. LangGraph Workflow

The v1 graph should be explicit and easy to debug.

```text
START
  |
  v
intake
  |
  v
plan_study
  |
  v
policy_check
  |
  v
human_approval
  |
  v
prepare_baseline
  |
  v
run_mesh
  |
  v
mesh_quality_gate
  |
  v
run_baseline
  |
  v
solver_health_gate
  |
  v
extract_baseline_qoi
  |
  v
mesh_refinement
  |
  v
mesh_independence_gate
  |
  v
run_parameter_cases
  |
  v
cross_case_analysis
  |
  v
review_results
  |
  v
final_report
  |
  v
END
```

Failure branches:

```text
solver_health_gate --fail--> diagnose_solver --> bounded_retry --> solver_health_gate
mesh_quality_gate --fail--> diagnose_mesh  --> bounded_mesh_fix --> mesh_quality_gate
validation_gate   --fail--> review_failure --> human_approval
```

In v1, all automatic retries must be **bounded**:

```text
max_solver_retries = 2
max_mesh_retries = 1
```

---

# 11. Human Approval Gate

The first study plan must require approval before simulations begin.

The approval object should contain:

```text
approved = true/false
approved_by
approved_at
plan_version
notes
```

A future UI can make this a web approval screen. For v1, CLI approval is enough.

The agent must not bypass the gate.

---

# 12. CFD Knowledge + Skills

Do not start with a vector database.

First implement **file-based Markdown skills**. This is simpler, transparent, and enough for the first working demo.

## Skill: cfd-planning.md

Must teach the agent:

- objective vs procedure,
- required inputs,
- permitted assumptions,
- mesh/model/numerical choices,
- what needs human approval,
- what must be validated.

## Skill: openfoam-run.md

Must define:

- case directory structure,
- allowed utilities,
- execution order,
- command timeouts,
- log handling,
- expected outputs.

## Skill: convergence-check.md

Must define deterministic checks for:

- residual trends,
- minimum/maximum fields,
- solver exit status,
- continuity or conservation indicators,
- required fields existing.

## Skill: mesh-independence.md

Must define:

```text
coarse -> medium -> fine
```

and compare the declared QoIs between levels.

Use a configurable tolerance in code rather than allowing the LLM to invent it at runtime.

## Skill: result-review.md

Must define how the review agent should cite evidence:

```text
Claim
Evidence file
Metric
Value
Threshold
Pass/fail
```

---

# 13. RAG — Add It After the Deterministic Workflow Works

Do **not** make RAG a dependency of the first CFD run.

Phase 1:

```text
Markdown skills + fixed case documentation
```

Phase 2:

```text
knowledge/*.md
       |
       v
chunk
       |
       v
embeddings
       |
       v
Local vector store
```

The RAG corpus should eventually contain:

- OpenFOAM documentation excerpts,
- project-specific CFD guidelines,
- validated case notes,
- mesh guidelines,
- numerical-method notes,
- previous run reports,
- accepted/rejected decisions.

Every RAG result must retain:

```text
source
section
chunk_id
content hash
```

The final report should be able to say which knowledge documents influenced a decision.

---

# 14. Gemini Integration

Use a single Gemini model initially.

The model is used for:

```text
planning
bounded diagnosis
result explanation
report drafting
```

It is NOT responsible for:

```text
running shell commands directly
calculating final validation metrics
choosing arbitrary numeric tolerances
writing outside allowed directories
accepting a failed validation gate
```

Keep the LLM client behind an interface:

```python
class LLMService:
    def structured_plan(...): ...
    def diagnose(...): ...
    def review(...): ...
```

This allows a different model/provider later without rewriting the workflow.

Environment variable:

```text
GEMINI_API_KEY=...
```

Never commit the key.

---

# 15. SQLite Checkpointing

For v1 use LangGraph's `SqliteSaver` from `langgraph-checkpoint-sqlite`. The current LangGraph reference describes SQLite as suitable for local development, testing, lightweight deployments, demos, and small projects. `SqliteSaver` is synchronous and intended for lightweight/small-project usage; an async saver is also available.

Recommended layout:

```text
data/
└── checkpoints.sqlite
```

Example setup:

```python
import sqlite3
from langgraph.checkpoint.sqlite import SqliteSaver

conn = sqlite3.connect("data/checkpoints.sqlite", check_same_thread=False)
checkpointer = SqliteSaver(conn)

graph = builder.compile(checkpointer=checkpointer)
config = {"configurable": {"thread_id": "demo-001"}}

result = graph.invoke(initial_state, config)
```

Create the `data/` directory before starting the application. Keep the checkpoint database out of Git. For safety, apply LangGraph's current strict message-pack/deserialization guidance when configuring the checkpointer, especially if a checkpoint database could ever be modified by an untrusted party.\n
SQLite is intentionally a **v1 decision**, not a forever architecture. Move to PostgreSQL later if we need concurrent workers, multiple application instances, centralized persistence, or production deployment.


Use LangGraph's SQLite checkpointer (`SqliteSaver`).

Recommended conceptual setup:

```text
SQLite
   |
   +-- LangGraph checkpoint tables
   +-- optional lightweight run metadata
```

Initialize the checkpointer once at application startup. Use a stable:

```text
thread_id = run_id
```

so that a paused workflow can resume exactly from its last checkpoint.

No database container is required for v1.
Use SQLite for the workflow checkpoint in v1. Keep the database file under `./data/checkpoints.sqlite` and do not store large CFD fields in it.

---

# 16. OpenFOAM Local Runtime

Because the target development environment is a Mac laptop, use Docker for OpenFOAM rather than relying on native macOS installation.

OpenFOAM Foundation documents Docker-based installation for macOS and provides an `openfoam11-macos` launcher. The Foundation also documents OpenFOAM 11 running the `pitzDailySteady` tutorial through Docker.

For maximum repeatability in the project, prefer a pinned Docker image/tag and project-mounted case directories once the exact image is verified on the machine.

On Apple Silicon, the currently listed `openfoam/openfoam11-graphical-apps:11` Docker image is published for `linux/amd64`, so Docker may need x86_64 emulation. Expect slower CFD execution than native ARM software.

Do not put ParaView GUI functionality on the critical path of the agent. Generate files/plots headlessly with Python/PyVista where practical.

---

# 17. OpenFOAM Runner Contract

Create one controlled Python wrapper:

```python
run_openfoam(case_dir: Path, operation: Literal["mesh", "check_mesh", "solve"])
```

The wrapper must:

1. Validate `case_dir`.
2. Validate operation.
3. Validate that the expected case files exist.
4. Start the pinned OpenFOAM container.
5. Mount only the project/run directory required for this case.
6. Capture stdout/stderr into files.
7. Capture return code.
8. Record elapsed time.
9. Enforce timeout.
10. Never delete source artifacts automatically.

Example output structure:

```text
runs/<run_id>/cases/case_001/
|
+-- input/
+-- case/
+-- logs/
|   +-- blockMesh.log
|   +-- checkMesh.log
|   +-- solver.log
|
+-- results/
+-- plots/
+-- metadata.json
+-- validation.json
```

---

# 18. Monitoring

Do not ask the LLM to parse an entire solver log every few seconds.

Create a deterministic monitor that extracts:

```text
iteration/time
continuity residual
U residual
p residual
other relevant residuals
Courant number if available
execution state
```

Persist a compact machine-readable file:

```json
{
  "status": "running",
  "latest_iteration": 1200,
  "latest_residuals": {
    "Ux": 1.2e-06,
    "Uy": 8.1e-07,
    "p": 3.4e-06
  },
  "residual_trend": "decreasing"
}
```

The LLM receives the compact summary rather than the full raw log unless diagnosis requires more context.

---

# 19. Deterministic Validation Gates

This is the heart of reliability.

## Gate A — Case integrity

Pass only if:

```text
required directories exist
required fields exist
required dictionaries exist
no unexpected case escape
```

## Gate B — Mesh quality

Use the OpenFOAM mesh checker and parse machine-readable/known text metrics.

At minimum capture:

```text
cells
faces
boundary faces
max skewness
max non-orthogonality
negative-volume cells
```

The exact pass criteria should be declared in configuration and reviewed by a human.

## Gate C — Solver health

Require:

```text
process exited successfully
no fatal error
required residuals found
residual trend acceptable
important fields contain finite values
```

## Gate D — Conservation

Calculate a declared conservation metric, for example mass-flow imbalance:

```text
imbalance = abs(m_in - m_out) / max(abs(m_in), epsilon)
```

Do not let the LLM invent the formula.

## Gate E — Mesh independence

For each declared QoI:

```text
relative_change = abs(Q_fine - Q_medium) / max(abs(Q_fine), epsilon)
```

The threshold should be configured, for example:

```yaml
mesh_independence:
  max_relative_change: 0.05
```

This 5% value is a **demo configuration**, not a universal CFD standard. Real engineering projects must define an appropriate tolerance for their QoIs.

## Gate F — Physics sanity

Start with simple checks:

```text
NaN/Inf absent
values inside declared physical bounds
pressure/velocity fields are present
expected flow direction is respected
```

This should never be the only validation.

---

# 20. Post-processing

Keep the first QoI set very small:

```text
pressure_drop
mass_flow_in
mass_flow_out
mass_imbalance
maximum_velocity
average_velocity
recirculation_length (only if robustly defined)
```

Create deterministic scripts that output:

```text
results/qoi.json
results/qoi.csv
plots/residuals.png
plots/pressure.png
plots/velocity.png
```

The agent interprets these artifacts; it does not calculate the primary metrics itself.

---

# 21. Parameter Sweep

After baseline + mesh-independence passes, execute:

```text
case_001: 10 m/s
case_002: 15 m/s
case_003: 20 m/s
```

The sweep definition should be a structured artifact:

```json
{
  "parameter": "inlet_velocity",
  "values": [10.0, 15.0, 20.0],
  "unit": "m/s",
  "reason": "study the effect of inlet speed",
  "bounds": {
    "min": 5.0,
    "max": 25.0
  }
}
```

The application validates those bounds before creating cases.

---

# 22. Agent Roles in v1

Keep it to **three logical agents**.

## 1. Planner Agent

Responsibilities:

- translate objective into a structured plan,
- propose cases,
- explain assumptions,
- identify required validation,
- request human approval.

Output:

```text
StudyPlan
```

## 2. Diagnostic Agent

Responsibilities:

- examine compact failure evidence,
- identify likely numerical/automation causes,
- propose only actions allowed by policy,
- never modify physics assumptions silently.

Output:

```text
Diagnosis
```

## 3. Review Agent

Responsibilities:

- read validated artifacts,
- explain trends,
- identify remaining uncertainty,
- produce an evidence-linked engineering summary.

Output:

```text
Review
```

Do not make separate “Mesh Agent”, “Physics Agent”, “Solver Agent”, etc. until there is a real need. Initially, deterministic tools + skills are enough.

---

# 23. Structured Outputs

Every LLM output must use a Pydantic schema.

Example planning schema:

```python
class StudyPlan(BaseModel):
    objective: str
    baseline_case: str
    cases: list[CaseSpec]
    mesh_levels: list[str]
    qois: list[str]
    permitted_parameters: list[str]
    assumptions: list[str]
    validation_plan: list[str]
    requires_human_approval: bool
```

Never parse free-form prose to decide whether to run a solver.

---

# 24. Decision / Audit Record

Every agent decision should have an evidence record like:

```json
{
  "decision_id": "dec_00017",
  "agent": "diagnostic_agent",
  "action": "retry_solver",
  "reason": "residuals stagnated and solver completed without convergence criteria",
  "evidence": [
    "logs/solver.log",
    "results/solver_health.json"
  ],
  "policy_check": "passed",
  "human_approval_required": false,
  "timestamp": "..."
}
```

This is the project's version of explainability: **what happened, why, what evidence was used, and which policy allowed the action**.

---

# 25. Artifact Contracts

Every stage writes one predictable artifact.

```text
study.json
plan.json
approval.json
case_manifest.json
mesh_report.json
solver_health.json
qoi.json
mesh_independence.json
sweep_results.json
review.json
audit.json
final_report.md
```

The next stage should validate the previous artifact before reading it.

Example:

```text
mesh_independence.json
{
  "status": "passed",
  "qois": {...},
  "threshold": 0.05,
  "evidence": [...]
}
```

---

# 26. Stage-Gate Rule

A stage can emit only one of:

```text
PASSED
FAILED
BLOCKED
```

`FAILED` means the workflow cannot proceed automatically.

`BLOCKED` means human intervention is required.

Do not introduce vague states such as `probably_ok`.

---

# 27. Error Handling Strategy

## Recoverable errors

Examples:

```text
container exited unexpectedly
transient process error
missing generated file
recoverable numerical instability
```

Allow bounded retry.

## Non-recoverable / dangerous errors

Examples:

```text
case path outside allowed directory
physics configuration unexpectedly changed
validation criteria missing
mesh has invalid cells
required field contains NaN/Inf
human approval missing
```

Stop the workflow.

---

# 28. Security Rules

The LLM must not receive unrestricted access to:

```text
home directory
SSH keys
Git credentials
.env contents
arbitrary Docker socket
arbitrary shell
```

The agent should be able to operate only inside:

```text
project/cfd_cases
project/runs/<run_id>
project/knowledge
```

Never mount `/var/run/docker.sock` into the agent application.

The host-side CFD runner is responsible for tightly controlled container execution.

---

# 29. Testing Strategy

The project is not considered “working” because one successful CFD run completed.

## Unit tests

Test:

```text
parameter validation
path validation
QoI calculations
conservation calculation
mesh-independence calculation
artifact validation
state serialization
```

## Integration tests

Use a tiny CFD case and verify:

```text
case creation
mesh generation
solver execution
log capture
QoI extraction
validation
```

## Workflow test

Mock the LLM and run the entire graph.

Verify:

```text
START -> ... -> END
```

without requiring Gemini.

## Real-model smoke test

Use Gemini only for:

```text
plan
review
```

and verify structured outputs.

---

# 30. Definition of Done for v1

The project is complete only when this command works:

```bash
python scripts/run_demo.py
```

and produces:

```text
runs/<run_id>/
|
+-- study.json
+-- plan.json
+-- approval.json
+-- cases/
|   +-- baseline_coarse/
|   +-- baseline_medium/
|   +-- baseline_fine/
|   +-- case_10ms/
|   +-- case_15ms/
|   +-- case_20ms/
|
+-- artifacts/
|   +-- mesh_report.json
|   +-- solver_health.json
|   +-- mesh_independence.json
|   +-- sweep_results.json
|   +-- review.json
|   +-- audit.json
|
+-- plots/
|   +-- residuals.png
|   +-- pressure.png
|   +-- velocity.png
|   +-- qoi_vs_velocity.png
|
+-- reports/
    +-- final_report.md
```

The run must be resumable after interruption.

The final report must explicitly state:

```text
What was run
What model/case was used
What changed between cases
Mesh levels used
Validation criteria
Validation results
Limitations
Agent decisions
Human approvals
```

---

# 31. Implementation Milestones

## Milestone 0 — Environment

Goal:

```text
Python + Docker + SQLite + OpenFOAM all verified.
```

Acceptance:

```text
docker compose up -d
psql connection works
OpenFOAM container can run blockMesh
OpenFOAM can run the chosen benchmark case
```

Do not proceed until this works.

---

## Milestone 1 — Deterministic CFD Runner

Implement:

```text
prepare_case
run_mesh
check_mesh
run_solver
extract_logs
```

No LLM yet.

Acceptance:

```bash
python scripts/smoke_test.py
```

runs CFD successfully.

---

## Milestone 2 — Deterministic Validation

Implement:

```text
solver_health
conservation
qoi
mesh_independence
```

Run these against known sample outputs.

Acceptance:

```bash
pytest
```

passes.

---

## Milestone 3 — LangGraph + SQLite

Build the graph using a mock planner first.

Add SQLite checkpointing.

Acceptance:

1. Start run.
2. Interrupt it.
3. Restart using same `run_id`.
4. Graph resumes instead of restarting from scratch.

---

## Milestone 4 — Gemini Planner

Add Gemini.

Planner receives:

```text
user goal
CFD skill
case capabilities
allowed parameters
validation rules
```

Planner emits validated `StudyPlan`.

Acceptance:

```text
bad parameter -> rejected
out-of-range parameter -> rejected
missing validation -> rejected
valid plan -> approval gate
```

---

## Milestone 5 — Agentic Workflow

Connect:

```text
planner -> policy -> human approval -> deterministic tools
```

The LLM decides *which allowed action comes next*; tools perform the actual work.

---

## Milestone 6 — Diagnostic Agent

Introduce controlled recovery.

Example injected failure:

```text
bad numerical setting
```

Expected flow:

```text
solver fails
  |
  v
diagnostic agent
  |
  v
proposed bounded change
  |
  v
policy check
  |
  v
retry
```

Acceptance:

```text
agent cannot change physics or leave run directory
```

---

## Milestone 7 — Mesh Independence

Automate:

```text
coarse
medium
fine
```

Run validation and persist the selected mesh result.

Acceptance:

```text
mesh_independence.json
```

contains objective evidence rather than an LLM conclusion.

---

## Milestone 8 — Parameter Sweep

Run the three inlet-velocity cases.

Produce:

```text
sweep_results.json
qoi_vs_velocity.png
```

---

## Milestone 9 — Review Agent

Feed only validated evidence to Gemini.

Prompt it to:

```text
summarize
explain trends
identify uncertainty
cite artifacts
avoid inventing physical claims
```

---

## Milestone 10 — Final Audit

Implement:

```text
stage_gate_audit.py
```

It verifies:

```text
all required artifacts exist
all gates passed
human approval exists
case paths are valid
result files exist
validation is recorded
```

Only then produce:

```text
final_report.md
```

---

# 32. Codex Working Method

Do **not** ask Codex:

> “Build the whole agentic CFD system.”

That is too broad and makes verification difficult.

Instead, drive Codex with one milestone at a time.

At the beginning of the repository, create `AGENTS.md` containing the project safety/architecture rules.

Every Codex task should follow this cycle:

```text
inspect
  ↓
plan
  ↓
implement
  ↓
test
  ↓
run real command
  ↓
inspect outputs
  ↓
fix
  ↓
commit
```

After each milestone, require Codex to show:

```text
files changed
commands executed
tests passed
real CFD evidence
remaining issues
```

---

# 33. Codex Prompt — Milestone 0

Paste this into Codex:

```text
You are working in a repository called agentic-cfd-local.

Read AGENTS.md first.

Task: implement Milestone 0 only.

Goal:
Verify the complete local development environment for the agentic CFD demo.

Requirements:
1. Python 3.11+ environment.
2. SQLite checkpoint database stored under `data/checkpoints.sqlite`.
3. OpenFOAM 11 local Docker execution suitable for macOS.
4. Create the project structure from the plan.
5. Add .env.example but never create or commit secrets.
6. Add a smoke-test script that verifies:
   - SQLite checkpoint database is created and writable.
   - OpenFOAM is reachable.
   - blockMesh can run for the chosen benchmark case.
   - the solver can be launched for the benchmark case.
7. Do not add LangGraph or Gemini yet.
8. Do not create a generic shell-execution tool.
9. Keep all CFD files under the repository.
10. Pin versions where practical.

Before modifying files:
- inspect the repository
- inspect Docker availability
- inspect the available OpenFOAM 11 image/launcher
- use the simplest working approach for this machine

After implementation:
- run the smoke tests for real
- report exact commands
- report exact outputs/errors
- do not claim success without executing the commands.
```

---

# 34. Codex Prompt — Milestone 1

```text
Implement only Milestone 1: deterministic OpenFOAM case runner.

No LLM.
No LangGraph.
No arbitrary shell tool.

Create narrow tools/functions:
- prepare_case
- run_mesh
- check_mesh
- run_solver
- collect_logs

Requirements:
- strict path validation
- case IDs must map to approved run directories
- parameters must be schema-validated
- subprocess/container execution must have timeouts
- stdout/stderr/return code must be persisted
- never delete raw logs automatically
- all commands must be allowlisted

Create tests for path traversal and invalid parameters.

Then run a real CFD case and save the artifacts under runs/.

Do not proceed to agentic behavior.
```

---

# 35. Codex Prompt — Milestone 2

```text
Implement deterministic validation only.

Create:
- convergence.py
- conservation.py
- mesh_independence.py
- qoi.py

Inputs must be files/artifacts generated by the CFD runner.

The functions must be deterministic and independently testable.

Implement Pydantic result models.

Create unit tests with synthetic data for:
- pass
- fail
- invalid input
- NaN/Inf
- zero denominators

Then run validation on a real OpenFOAM result.

Do not use Gemini and do not ask the LLM to calculate validation metrics.
```

---

# 36. Codex Prompt — Milestone 3

```text
Implement the LangGraph workflow skeleton and SQLite checkpointing.

Requirements:
- explicit typed state
- nodes corresponding to the workflow plan
- SQLite `SqliteSaver` checkpointer
- thread_id equals run_id
- mock planner
- deterministic tools
- resume test

Add a test that interrupts after a known node and resumes from SQLite.

The workflow must be observable using structured logging.

Do not integrate Gemini yet.
```

---

# 37. Codex Prompt — Milestone 4

```text
Integrate Gemini only for structured study planning.

Requirements:
- GEMINI_API_KEY from environment only
- one model configuration
- Pydantic structured output
- planner prompt loaded from skills/prompts rather than hardcoded in Python
- reject invalid/out-of-range plans before execution
- no arbitrary command generation
- no direct filesystem tool for the LLM

Add tests using a mocked LLM response for malformed and valid plans.

Run one real Gemini planning call and save plan.json.
```

---

# 38. Codex Prompt — Milestone 5

```text
Connect the planner to the deterministic CFD workflow.

Rules:
- LLM proposes actions only from an allowlisted action set.
- A policy gate verifies every action.
- Deterministic Python tools execute the actions.
- Human approval is required before the first CFD execution.
- Every action gets an audit record.
- Every stage writes an artifact contract.

Run the complete baseline workflow for real.

Do not add automatic solver recovery yet.
```

---

# 39. Codex Prompt — Milestone 6

```text
Add the Diagnostic Agent.

Inject one controlled solver failure in a test case.

The agent may only propose changes from this allowlist:
- relaxation setting
- numerical solver setting
- time/iteration control

It must NOT change:
- geometry
- boundary conditions
- physical model
- material properties
- validation thresholds

Every proposed action must pass a deterministic policy checker before execution.

Bound retries to 2.

Demonstrate the recovery with an integration test and a real run.
```

---

# 40. Codex Prompt — Milestone 7/8

```text
Implement mesh-independence and parameter sweep orchestration.

Baseline:
- coarse
- medium
- fine

Then parameter sweep:
- inlet velocity 10, 15, 20 m/s

The workflow must:
1. run cases
2. extract QoIs
3. calculate mesh independence deterministically
4. refuse to continue when the required gate fails
5. aggregate results
6. generate plots

Do not let the LLM calculate the metrics.
```

---

# 41. Codex Prompt — Milestone 9/10

```text
Implement the Review Agent and final audit.

Review Agent receives only validated artifacts and selected plots.

It must:
- summarize what was actually run
- identify trends supported by the data
- identify limitations
- identify failed or skipped validation
- reference artifact paths
- never invent measurements

Implement the final stage-gate audit.

A final_report.md must be generated only if all required gates pass.

Add an integration test that deliberately removes a required artifact and verifies that the final report is blocked.
```

---

# 42. Recommended CLI

Target commands:

```bash
# No database service startup is required for v1. SQLite is file-based.
make db-up

# Verify environment
make smoke

# Run deterministic CFD only
python scripts/run_case.py --case baseline --mesh medium

# Run tests
pytest -q

# Start a new agentic study
python scripts/run_demo.py \
  --goal "Study the effect of inlet velocity on pressure drop and flow separation"

# Resume
python scripts/run_demo.py --resume <run_id>

# Inspect run
python scripts/show_run.py <run_id>
```

A Makefile is optional, but the commands should remain simple.

---

# 43. What “Reliable” Means in This Project

Reliability does NOT mean:

```text
LLM is smart
```

It means:

```text
LLM proposes
     |
     v
schema validation
     |
     v
policy validation
     |
     v
controlled tool
     |
     v
deterministic execution
     |
     v
deterministic validation
     |
     v
LLM interpretation
```

This is the architecture to keep throughout the project.

---

# 44. What to Add After v1

Only after v1 is stable, add features in this order.

## v2 — RAG

Use a local vector store later (for example Chroma/FAISS) or SQLite-backed metadata. Do not add vector infrastructure until the core CFD workflow works end-to-end.

Add:

```text
OpenFOAM docs
CFD guidelines
validated historical cases
```

## v3 — More CFD Skills

Add specialized skills for:

```text
mesh selection
boundary condition selection
turbulence model guidance
numerical scheme guidance
```

These should recommend options and require policy/human approval for meaningful physics changes.

## v4 — Automated Design Space Exploration

Add:

```text
parameter sweeps
Latin hypercube
Bayesian optimization
```

But maintain the validation gates.

## v5 — Surrogate Model

After accumulating enough validated runs:

```text
CFD database
    |
    v
ML surrogate
    |
    v
cheap screening
    |
    v
CFD verification of finalists
```

## v6 — Plasma Process Case

Only after the general CFD workflow is dependable.

Introduce:

```text
plasma-specific physics
species transport
reaction/chemistry
energy
surface effects
```

At this stage the project becomes much closer to the Exeter/OIPT target.

---

# 45. Suggested Final Architecture

The mature local system should become:

```text
                         USER
                          |
                          v
                 +------------------+
                 | LangGraph        |
                 | Study Manager    |
                 +---------+--------+
                           |
          +----------------+----------------+
          |                                 |
          v                                 v
   +-------------+                   +-------------+
   | Planner     |                   | Reviewer    |
   | Agent       |                   | Agent       |
   +------+------+                   +------+------+ 
          |                                 ^
          v                                 |
   +-------------+                           |
   | Policy      |                           |
   | Engine      |                           |
   +------+------+                           |
          |                                  |
          v                                  |
   +-------------+                           |
   | CFD Tools   |---------------------------+
   +------+------+          validated data
          |
   +------+-----------------------------+
   |                  |                 |
   v                  v                 v
OpenFOAM            Monitor          Validation
   |                  |                 |
   +------------------+-----------------+
                      |
                      v
                 Artifacts
                      |
            +---------+----------+
            |                    |
            v                    v
       SQLite                 Filesystem
       checkpoints            CFD/results
            |                    |
            +---------+----------+
                      |
                      v
                Final Report
```

---

# 46. Key Lessons to Keep From AI-CFD-Scientist

Use these ideas as design references, not as code to blindly copy:

1. **Stage the workflow.** Do not build one giant agent loop.
2. **Use artifact contracts.** Each stage produces explicit structured evidence.
3. **Make mesh independence an actual gate.**
4. **Separate execution from interpretation.**
5. **Keep case directories isolated.**
6. **Use deterministic validators.**
7. **Make runs resumable.**
8. **Use bounded retries.**
9. **Keep human approval around high-impact decisions.**
10. **Build skills as domain knowledge + procedure.**
11. **Audit the whole run.**
12. **Do not allow the LLM to silently simplify physics just to make a solver converge.**

The repository currently implements many of these concepts, including a mesh-independence gate, planner/reviewer loops, case runners, stage-gate auditing, skills, and checkpointed LangGraph orchestration.

---

# 47. Reference Links

## AI-CFD-Scientist

https://github.com/csml-rpi/AI-CFD-Scientist

## AI-CFD-Scientist AGENTS.md

https://github.com/csml-rpi/AI-CFD-Scientist/blob/main/AGENTS.md

## AI-CFD-Scientist skills

https://github.com/csml-rpi/AI-CFD-Scientist/tree/main/cfd-skills

## AWS agentic CFD article

https://aws.amazon.com/blogs/hpc/accelerating-cfd-development-from-years-to-weeks-with-agentic-ai-and-aws/

## LangGraph SQLite checkpoint

https://reference.langchain.com/python/langgraph.checkpoint.sqlite

## Google Gemini API

https://ai.google.dev/gemini-api/docs/get-started

## OpenFOAM 11 macOS / Docker

https://openfoam.org/download/11-macos/

## OpenFOAM 11 Linux / Docker

https://openfoam.org/download/11-linux/

## OpenFOAM Docker images

https://hub.docker.com/r/openfoam/openfoam11-graphical-apps/tags

---

# 48. Final Execution Order

Follow this order exactly:

```text
0. Environment
   |
1. Deterministic OpenFOAM runner
   |
2. Deterministic validation
   |
3. LangGraph + SQLite
   |
4. Gemini planner
   |
5. Agentic orchestration
   |
6. Diagnostic/retry agent
   |
7. Mesh independence
   |
8. Parameter sweep
   |
9. Review agent
   |
10. Final audit/report
   |
11. RAG
   |
12. More CFD skills
   |
13. Optimization
   |
14. Plasma-specific workflow
```

**Do not skip directly to multi-agent automation.** The deterministic CFD runner + validation layer is the foundation that makes the agentic layer trustworthy.

