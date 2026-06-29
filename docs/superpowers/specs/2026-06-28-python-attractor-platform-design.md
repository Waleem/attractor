# Python Attractor Platform Design

## Summary

This design describes a phased product direction for extending the existing Python
Attractor implementation into a small-team workflow operations platform. The
platform keeps the workflow engine, execution runtime, API server, persistence,
sandboxing, and workflow-control logic Python-based, while allowing a React/Vite
frontend for the web console.

The product adopts Fabro-style local workflow and operations conventions where
they fit the Python implementation: repo-local workflow packages, local execution
as a first-class mode, git-worktree isolation for safe local runs, Docker sandbox
execution for shared mutating runs, git-backed checkpoints, durable run history,
approvals, artifacts, and an operations-oriented GUI. It does not attempt full
Fabro feature parity in the first release. Instead, it builds a foundation that
can later support cloud sandboxes, SSH/preview links, natural-language specs, PR
automation, and broader SDLC control-plane features.

## Product Direction

The first real product version optimizes for a small engineering team sharing
versioned workflows, run history, approvals, and reusable specs across multiple
repos. The primary workflow is reliable execution of agent workflows: define DOT
workflows, run them against repos, observe progress, approve gates, inspect
artifacts, and preserve history.

The source of truth remains the repository. Workflow definitions live in a
repo-local `.attractor/` directory and can be reviewed through normal code review
processes. The shared server indexes those files, launches runs, records history,
coordinates approvals, manages artifacts, and applies approved changes back to
registered local repos when safe.

The first shared deployment target is a single trusted-LAN server running a
FastAPI backend, Postgres, artifact storage, and local Docker. No authentication
is required for Phase 1 or Phase 2, but all approval and write-back records accept
an optional `actor_label` so user attribution can be added later without
rewriting the audit model.

## Phases

The phases follow the dependency order in Appendix B. The two Phase 1-to-2
spines are durability and isolation. Durability enables run history, API
resources, queueing, artifacts, and GUI replay. Isolation enables safe execution,
git checkpoints, branch-backed write-back, and eventual PR automation. The Phase
2 trusted-LAN preview ends with approved branch promotion, so worktree isolation
and git checkpointing cannot be deferred to a vague later phase.

### Phase 1: Engine Contracts and Parity Audit

Phase 1 stabilizes the current Python engine around the contracts needed by the
shared platform. This is targeted product-oriented hardening, not generic
refactoring.

Phase 1 deliverables:

1. Stable public APIs, config objects, and error types.
2. `RunSpec` as the immutable run manifest.
3. Variable-expansion parity audit against Fabro's MiniJinja-based behavior,
   with explicit decisions for escaping and nested interpolation.
4. Validation/lint parity audit against Fabro's workflow lint rules.
5. Regression coverage preserving the existing local CLI/library pipeline path.

The existing local pipeline execution capability remains first-class. Phase 1
must not force Docker on the CLI or library APIs.

### Phase 1-to-2: Durability and Isolation Spines

The durability spine introduces Postgres-backed `RunRecord` and append-only
`RunEvent`, a filesystem artifact-store interface, and centralized redaction for
events/logs before persistence.

The isolation spine introduces git-worktree local isolation and a stable
`RunEnvironment` interface. The current `LocalEnvironment` is raw host execution;
it remains useful for CLI/dev/trusted workflows, but the shared server needs a
worktree-backed local mode so agent mutations happen on a managed branch rather
than directly in the registered repo.

These spines should be built in parallel. They unblock the Phase 2 platform
surface and the safe write-back milestone.

### Phase 2: Shared Server, Git Checkpoints, and Operations Console

Phase 2 introduces the platform surface:

1. Git checkpointing with per-stage commits to managed refs for resume, revert,
   and trace.
2. Docker wired through `RunEnvironment` for shared mutating runs.
3. Durable run queue for 24/7 background runs.
4. `.attractor/project.toml` plus per-workflow `workflow.toml`, including the
   server-owned environment domain.
5. Secret vault and workflow-visible variables.
6. FastAPI resources for repos, workflows, runs, events, approvals, artifacts,
   cancellation, settings, health, capacity, and write-back.
7. SSE repointed to durable events.
8. Persistent `ApprovalDecision` records.
9. React/Vite Operations Console.
10. Branch-from-worktree write-back after human approval.

The GUI center of gravity is an Operations Console: active runs, queued runs,
approvals, queue health, failures, artifacts, branch/write-back review, and
system settings. Repo catalog and graph inspection are supporting views rather
than the home screen.

### Phase 3: Factory Features and Fabro UX Attachments

Phase 3 builds factory features and late-attached Fabro UX capabilities on top
of the reliable runner:

1. GitHub auth and PR automation: branch -> commit -> PR with run evidence.
2. Scheduled automations and cron-style recurring runs.
3. MCP client support for external tool servers.
4. User lifecycle hooks, including `project.toml [[run.hooks]]` and
   `post_tool_use`.
5. Spec and work-order interview flows that launch workflows from the generated
   repo-local work.
6. Steering API and console steer bar that expose the engine's existing steering
   queue for mid-turn intervention.
7. Review and repair loops: automated code review, test failure triage, and
   iterative repair workflows.

### Phase 4: Control Plane and Remote Execution

Phase 4 expands toward an SDLC control plane: organization-wide traceability,
governance, living requirements, decision history, cross-repo visibility,
policy, roles, SSO, cloud or remote sandbox adapters, SSH/preview links, Slack
or tracker integrations, object-native storage adapters such as SlateDB, and
deeper SDLC reporting.

## Repo Workflow Layout

The canonical repo-local workflow layout is:

```text
.attractor/
  project.toml
  workflows/
    release-checks/
      workflow.dot
      workflow.toml
    test-repair/
      workflow.dot
      workflow.toml
  prompts/
  specs/
  templates/
  policies/
```

This mirrors Fabro's split between project-level and workflow-level
configuration while adapting the directory name to this Python project.

`project.toml` is repo-level configuration. It owns settings that should be
shared across workflows:

- server-managed environments
- resource limits
- allowed execution modes
- shared variables
- hook definitions such as `[[run.hooks]]`
- default retention and artifact policy
- repo-wide integration defaults

`workflow.dot` is required and remains the executable Attractor graph.
`workflow.toml` is optional. If TOML is absent, the server infers the workflow
name from the directory and applies project/platform defaults.

`workflow.toml` owns workflow-local metadata and platform configuration, such as:

- display name and description
- tags
- required inputs
- default provider and model
- approval policy
- write-back policy
- artifact paths
- retention policy

The DOT graph should remain focused on workflow control flow and prompts.
Operational configuration should move to TOML when it affects the platform rather
than the graph semantics. Repo-wide platform configuration belongs in
`project.toml`; per-workflow overrides belong in `workflow.toml`.

## Core Components

### RegisteredRepo

`RegisteredRepo` represents a local path that the shared server is allowed to
operate on. It records:

- id
- name
- local path
- default branch
- current commit
- dirty-state status
- last indexed timestamp
- project config status
- discovered workflow packages

Phase 1 and Phase 2 support local path registration only. Git remote registration
is a later extension.

### ProjectConfig

`ProjectConfig` represents `.attractor/project.toml`. It records repo-level
configuration that multiple workflows share:

- named environments
- resource limits
- shared variables
- write-only secret references
- lifecycle hooks
- default retention policy
- default artifact policy
- integration defaults

`ProjectConfig` is part of the Phase 1-to-2 config spine because environments,
hooks, secrets, variables, and server settings all depend on it.

### WorkflowPackage

`WorkflowPackage` represents a discovered workflow under
`.attractor/workflows/<name>/`. It records:

- repo id
- workflow name
- DOT path
- optional TOML path
- parsed TOML config
- effective project config reference
- validation status
- validation diagnostics

The workflow is valid only when `workflow.dot` exists and the DOT graph validates.
TOML validation failures do not execute with partial configuration; they are
reported as workflow validation errors.

### RunSpec

`RunSpec` is the immutable launch request. It records:

- repo id
- workflow id or workflow reference
- source commit
- dirty-state at launch
- input values
- actor label
- requested run environment
- effective run environment
- worktree branch
- checkpoint refs
- retention policy
- approval policy
- write-back policy

Runs are pinned to the recorded source commit. If the registered repo moves
before write-back, write-back must fail until the operator resolves the mismatch.
`actor_label` must be threaded through run launch, events, approvals, and
branch-backed write-back because it is the one future auth/SSO concern that is
not cheap to retrofit.

### ExecutionRun and RunEnvironment

`ExecutionRun` is the runtime instance of a workflow execution. It uses a
`RunEnvironment` behind a stable interface:

```text
RunEnvironment
  local   -> direct host execution for CLI/dev plus worktree-isolated local
             execution for shared-server runs
  docker  -> local Docker sandbox per run, default for shared mutating workflows
  remote  -> future cloud VM or remote sandbox adapter
```

Local execution remains first-class for the Python engine and CLI. The current
raw-host `LocalEnvironment` remains valid for CLI/dev/trusted workflows. The
shared server's local mode must be git-worktree isolated so agent mutations occur
on a managed branch, not directly in the registered repo. The shared server
defaults to Docker for workflows that can mutate code. Workflow TOML may request
an environment, but server policy can enforce a stricter environment.

### RunRecord and RunEvent

`RunRecord` stores durable operational state in Postgres. `RunEvent` is an
append-only durable event record. SSE streams are projections of persisted events,
not the primary source of truth.

Events include:

- queued, prepared, started, completed, failed, and cancelled transitions
- node lifecycle events
- LLM and tool activity
- logs
- retries
- human gates
- approval answers
- artifact creation
- errors
- checkpoint references
- write-back decisions

Python's current engine `Checkpoint` and `CheckpointSaved` event represent
in-memory pipeline resume state. They are useful but semantically different from
Fabro-style git checkpoints. Phase 2 adds git-backed per-stage commits to
managed refs for resume, revert, and trace.

### ArtifactRecord

`ArtifactRecord` stores metadata in Postgres and content in filesystem or object
storage. Default retention captures trace plus artifacts. Workflows may request a
full retained workspace bundle for important runs or selected failure classes.

Artifacts include:

- patches and diffs
- generated files
- summaries
- test output
- logs
- optional retained workspace bundles

SlateDB is not part of the Phase 1 critical path. It remains a future optional
adapter candidate for object-native event or artifact-heavy storage once the
platform needs that behavior.

### ApprovalDecision

`ApprovalDecision` records human gate responses and write-back approvals. It
stores:

- run id
- question or approval prompt
- answer or decision
- actor label
- timestamp
- related node or gate
- whether write-back was authorized

Formal user accounts are not required in Phase 1 or Phase 2, but the data model
preserves a place for later attribution.

### WriteBackPlan

`WriteBackPlan` represents approval to promote a run's managed worktree branch,
not approval to patch arbitrary files into the live registered repo. The agent
works in a git worktree on a branch created from the recorded base commit. Human
approval makes that branch available as the accepted output of the run. Phase 3
PR automation turns the same branch into a commit/PR with run evidence.

Branch-from-worktree is safer than patch-apply-to-dirty-repo because the
registered repo is not mutated during agent execution, the base commit is fixed,
checkpoint commits and run artifacts are tied to the branch, and conflicts stay
visible as Git state instead of partial filesystem edits.

Write-back/branch promotion must refuse to proceed when:

- the registered repo path is missing
- the managed worktree is missing
- the managed branch is not based on the run's recorded base commit
- the registered repo cannot see the managed branch/ref
- branch promotion would overwrite an existing protected branch
- filesystem permissions prevent the write

The trusted-LAN preview's final step is branch-backed write-back. Pull request
creation waits for Phase 3, but it should reuse this branch rather than invent a
separate patch mechanism.

## Runtime Behavior

Runs move through explicit states:

```text
queued
preparing
running
waiting_for_approval
completed
failed
cancelled
writeback_pending
writeback_applied
writeback_failed
```

The server appends durable events as state changes happen. The GUI reads the
current state through REST APIs and subscribes to live updates through SSE.

Run failures are categorized so users can distinguish platform failures from
workflow failures:

- workflow validation errors: invalid DOT, missing workflow files, bad TOML, or
  unsupported config
- environment preparation errors: missing repo path, dirty repo when clean is
  required, Docker unavailable, image pull failure, or workspace copy failure
- runtime errors: LLM/provider failure, tool failure, timeout, cancellation,
  failed human gate, or retry exhaustion
- artifact errors: patch generation failure, oversized artifact, or retention
  failure
- checkpoint errors: git checkpoint commit failure, managed ref failure, or
  resume/revert failure
- write-back errors: missing worktree, branch base mismatch, branch promotion
  conflict, protected branch collision, or filesystem permission failure

Every failed run preserves enough context to debug: final status, error category,
user-facing message, safe internal detail, last node, last event, and available
artifacts.

Cleanup is policy-based. The platform always retains the durable trace and
selected artifacts. Full workspace bundles are retained only when requested by
workflow or run policy, or when a selected failure class requires extra debugging
context.

## FastAPI Backend

The backend should expose product APIs around repo registration, workflow
discovery, runs, durable events, approvals, artifacts, write-back, settings, and
capacity. The existing Starlette server can either be wrapped or evolved into
FastAPI, but the final Phase 2 surface should be FastAPI.

Initial API resources:

```text
/api/repos
/api/repos/{repo_id}/project-config
/api/repos/{repo_id}/workflows
/api/workflows/{workflow_id}/validate
/api/runs
/api/runs/{run_id}
/api/runs/{run_id}/events
/api/runs/{run_id}/approvals
/api/runs/{run_id}/artifacts
/api/runs/{run_id}/checkpoints
/api/runs/{run_id}/cancel
/api/runs/{run_id}/writeback
/api/runs/{run_id}/steer
/api/settings/models
/api/settings/integrations
/api/settings/sandboxes
/api/settings/environments
/api/settings/variables
/api/settings/secrets
/api/settings/server
/api/settings/security
/api/settings/storage
/api/settings/monitoring
/api/system/health
/api/system/capacity
```

The API has no authentication requirement in the first trusted-LAN release, but
approval and write-back endpoints accept `actor_label`.

The steering endpoint can be added once the FastAPI run surface exists. The
engine already has a steer queue; Phase 3 exposes it through an API and console
steer bar.

## React Operations Console

The Phase 2 GUI is a React/Vite application. It is not server-rendered and does
not need to be Python-based. Its job is to make the shared workflow server easy
to operate.

Primary screens:

- Home: active runs, queued runs, waiting approvals, recent failures, Docker and
  worktree capacity, and retention warnings
- Runs: run list and run detail with timeline, graph/node status, logs, model
  and tool activity, checkpoint history, errors, steering, and cancellation
- Approvals: pending human gates and write-back approvals
- Artifacts: branch diff viewer, generated files, test output, summaries,
  retained bundles, and approved branch promotion action
- Repos: registered local paths, Git commit, dirty-state status, index status,
  and discovered workflow packages
- Workflow Detail: DOT validation, optional TOML metadata, required inputs,
  default environment, retention, approval/write-back policy, and launch form
- Settings: operational admin area
- System: health and capacity summary

The Settings area includes:

- Models: LLM providers, default models, and credential status
- Integrations: GitHub, Slack, webhooks, MCP servers, and future service
  connections
- Sandboxes: execution backends, including local, Docker, and future remote
  environments
- Environments: server-managed runtime definitions, local worktree settings, and
  Docker images
- Variables: non-sensitive values available to workflow configuration
- Secrets: write-only secret values injected into approved workflow runs
- Server: base URL, listen address, scheduler mode, and trusted-LAN mode
- Security: current no-auth posture, actor labels, allowed repo roots, and later
  auth controls
- Storage: Postgres, artifact storage, retention, cleanup, and future SlateDB
  adapter posture
- Monitoring: CPU, memory, disk, Docker capacity, and run concurrency
- Live Events: real-time system event stream

The prototype created during brainstorming is a disposable visual aid, not a
production implementation artifact.

## Persistence

Postgres is the primary operational database for shared server metadata and audit
records. It stores repos, project config metadata, workflow package metadata, run
records, run events, approval decisions, artifact metadata, checkpoint metadata,
settings, automation metadata, and write-back records.

Artifacts are stored on filesystem or object storage. The design should keep the
artifact store behind a small interface so local filesystem storage can work
first and object storage can be added later.

SQLite can still be useful for local development or test fixtures, but Postgres
is the first-class shared-server database.

## Security Posture

Phase 1 and Phase 2 assume a trusted LAN and no formal authentication. This
keeps the first shared server simple. The design still records `actor_label` on
run launch, approvals, and write-back decisions.

Security boundaries that are required even without auth:

- registered repo roots restrict what paths the server can operate on
- worktree isolation keeps local shared-server execution off the live repo path
- shared mutating workflows default to Docker
- secrets are write-only from the GUI perspective
- write-back promotes managed branches rather than patching arbitrary live files
- unsafe artifacts and oversize artifacts are handled by retention policy
- server settings should make the current no-auth posture explicit

Roles, SSO, organization governance, and policy enforcement beyond these
guardrails are Phase 4 work.

## Testing

Phase 1 tests:

- contract tests for `RunEnvironment` across direct local, worktree-isolated
  local, and Docker
- workflow package loader tests for required DOT, optional workflow TOML, and
  repo-level project TOML
- variable-expansion and validation/lint parity audits against Fabro behavior
- durable event model tests for ordering, replay, state transitions, and SSE
  projection
- artifact tests for patches, logs, summaries, retained workspace bundles, and
  retention cleanup
- git checkpoint tests for per-stage commit creation, managed refs,
  resume/revert/trace metadata, and failure handling
- branch-backed write-back tests for branch creation, promotion, protected branch
  collision, base commit mismatch, and missing worktree
- regression tests for existing local CLI and library behavior

Phase 2 tests:

- FastAPI API tests for repos, workflows, runs, events, approvals, artifacts,
  cancellation, write-back, settings, health, and capacity
- Postgres integration tests for run records, event append/replay, and artifact
  metadata
- Docker integration tests for actual per-run workspaces
- durable queue tests for restart-safe queued/background runs
- React route and component tests for Home, Runs, Approvals, Artifacts, Repos,
  Workflow Detail, Settings, and System
- end-to-end tests for register repo, index workflow, launch run, approve gate,
  inspect artifacts, and promote the managed branch

## Rollout

The first usable milestone is a trusted-LAN preview that can:

1. register a local repo path
2. discover `.attractor` workflow packages
3. validate a workflow
4. launch a run using direct local, worktree-local, or Docker execution as
   policy allows
5. stream and persist durable events
6. create git checkpoints for executed stages
7. pause for a human gate
8. capture artifacts
9. approve write-back
10. safely promote the managed worktree branch

The preview should favor boring completeness over breadth. It should not include
PR creation, cloud sandboxes, SSO, Git remote repo management, MCP, lifecycle
hooks, scheduled automations, or natural language work-order generation. Those
features build on the stable runner in later phases.

## Open Design Decisions For Later

These decisions are intentionally deferred:

- whether cloud sandboxing uses remote Docker hosts, VMs, or a third-party
  sandbox service
- whether PR automation uses local Git commands, GitHub API integration, or both
- whether SlateDB becomes useful for object-native event or artifact storage
- how the control plane models cross-repo requirements, decisions, and policies
- when to introduce local users, roles, and SSO

## Appendix A: Fabro Capability Parity and Phase Matrix

Status legend:

- ✅ Have -- exists in Python at usable parity
- ⚠️ Partial / Different -- exists but narrower, or different semantics than Fabro
- ❌ Absent -- no Python analog
- ➖ N/A -- Rust-specific infrastructure with no required Python analog

"Target phase" is the phase this document commits to. Where it diverges from the
prose roadmap, the divergence is called out as **[doc gap]**.

### A.1 Workflow engine and execution core

|Capability|Fabro crate(s)|Python today|Gap and target phase|
|---|---|---|---|
|DOT graph parse + typed model|`fabro-graphviz`|✅ `attractor_pipeline/parser`, `graph.py`|-- (Have)|
|Multi-stage pipeline runner|`fabro-workflow`, `fabro-core`|✅ `engine/runner.py`|-- (Have)|
|Conditions / branching / loops|`fabro-workflow`|✅ `conditions.py`, `transforms.py`|-- (Have)|
|Parallelism / fan-out / fan-in|`fabro-workflow`|✅ `handlers/parallel.py`|-- (Have)|
|Supervisor / subagent (child runs)|`fabro-agent`|✅ `subagent.py`, `subagent_manager.py`|-- (Have)|
|Variable expansion / templating|`fabro-variable`, `fabro-template`|⚠️ `variable_expansion.py` (custom, not MiniJinja)|Confirm feature parity (escaping, nested); P1|
|Graph validation / lint rules|`fabro-validate`|⚠️ `validation.py` (spec checks; fewer lint rules)|Port Fabro lint set; P1|
|Run manifest construction|`fabro-manifest`|❌ (assembled ad-hoc)|Formalize `RunSpec` as manifest; P1-P2|

### A.2 Sandboxing and environments

|Capability|Fabro crate(s)|Python today|Gap and target phase|
|---|---|---|---|
|Local execution|`fabro-sandbox` (`local.rs`)|⚠️ `LocalEnvironment` = direct host, **no worktree isolation**|Add git-worktree local mode; P1-P2|
|Worktree isolation for runs|`fabro-sandbox` (`worktree.rs`)|❌|Build; **P1-P2 [doc gap -- doc leaves local as raw host exec]**|
|Docker sandbox per run|`fabro-sandbox` (`docker.rs`)|⚠️ `DockerEnvironment` exists but not wired to runs|Wire to `RunEnvironment.docker`; P2|
|Cloud sandbox (Daytona)|`fabro-sandbox` (`daytona/`)|❌|`RunEnvironment.remote` adapter; P4|
|Server-owned environment domain|`fabro-environment`|❌|`project.toml [environments.*]`; P2|
|SSH into sandbox|`fabro-cli sandbox ssh`|❌|P4|
|Preview links / port expose|`fabro-cli sandbox preview`|❌|P4|

### A.3 Run state, history and observability

|Capability|Fabro crate(s)|Python today|Gap and target phase|
|---|---|---|---|
|Durable run records|`fabro-store`, `fabro-types`|❌ in-memory `pipeline_manager._runs`|Postgres `RunRecord`; P1-P2|
|Append-only durable events|`fabro-store`|⚠️ in-memory `events.py` (not persisted)|Durable `RunEvent`; P1-P2|
|SSE event streaming|`fabro-server`|✅ `server/sse.py` (projection of in-mem)|Repoint to durable events; P2|
|Git checkpoints per stage (resume/revert/trace)|`fabro-checkpoint`|⚠️ in-memory `Checkpoint`/`CheckpointSaved` only -- **not git-backed**|Build git checkpointing; **P2 [doc gap -- doc lists under "open decisions later"]**|
|Artifact storage + metadata|`fabro-store` (`artifact_store.rs`)|❌|`ArtifactRecord` + fs/object store; P2|
|Object-native store backend|`fabro-store` (`slate/`, SlateDB)|❌|Optional adapter; P4 (Postgres first)|
|Telemetry / analytics / crash|`fabro-telemetry`|❌|Optional; P4|
|Secret/credential redaction|`fabro-redact`|⚠️ env-suffix redaction in `tools/core.py`|Centralize redaction layer; P2|

### A.4 Human-in-the-loop and steering

|Capability|Fabro crate(s)|Python today|Gap and target phase|
|---|---|---|---|
|Approval / human gates|`fabro-workflow`|✅ `handlers/human.py`|Persist decisions (`ApprovalDecision`); P2|
|Interview steps (structured input)|`fabro-interview`|✅ `server/interviewer.py`|Surface in GUI; P2-P3|
|Mid-turn steering of running agent|`fabro-agent` + web `steer-bar`|⚠️ steer queue in `session.py`/`manager.py`, **no API/UI**|Expose via API + console; **P3 [doc gap -- not mentioned]**|
|Slack interviewer channel|`fabro-slack`|❌|P4 (Settings -> Integrations)|

### A.5 LLM and model routing

|Capability|Fabro crate(s)|Python today|Gap and target phase|
|---|---|---|---|
|Unified multi-provider client|`fabro-llm`|✅ `attractor_llm` (anthropic/openai/gemini/compat)|-- (Have)|
|Model catalog / resolution|`fabro-model`|✅ `attractor_llm/catalog.py`|-- (Have)|
|CSS-like model stylesheet routing|`fabro-llm`|✅ `stylesheet.py`|-- (Have)|
|Retry / fallback chains|`fabro-llm`|✅ `retry.py`, `middleware.py`|-- (Have)|
|Provider credential storage/resolution|`fabro-auth`, `fabro-vault`, `fabro-oauth`|⚠️ env-var only|Settings -> Models credential store; P2|
|ACP backend (agent client protocol)|`fabro-acp`|❌|Out of scope unless needed; P4|

### A.6 Tools and extensibility

|Capability|Fabro crate(s)|Python today|Gap and target phase|
|---|---|---|---|
|Core dev tools (read/write/edit/shell/grep/glob)|`fabro-tool`|✅ `attractor_agent/tools`|-- (Have)|
|apply_patch tool|`fabro-tool`|✅ `tools/apply_patch.py`|-- (Have)|
|MCP client (external tool servers)|`fabro-mcp`|❌|Build; **P3 [doc gap -- not mentioned]**|
|MCP stdio server (expose Fabro as MCP)|`fabro-mcp-server`|❌|P4|
|Server-managed MCP catalog|`fabro-mcp-store`|❌|P4 (Settings -> Integrations)|
|User lifecycle hooks (post_tool_use scripts)|`fabro-hooks`|❌ (only LLM middleware hooks)|`project.toml [[run.hooks]]`; **P3 [doc gap]**|

### A.7 Integrations

|Capability|Fabro crate(s)|Python today|Gap and target phase|
|---|---|---|---|
|GitHub App auth + API|`fabro-github`|❌ (grep hits were the word "issue")|P3 (PR automation)|
|PR creation from approved changes|`fabro-cli` + `fabro-github`|❌|P3|
|Issue tracker integration|`fabro-tracker`|❌|P4|
|Slack socket mode|`fabro-slack`|❌|P4|

### A.8 Secrets, variables and config

|Capability|Fabro crate(s)|Python today|Gap and target phase|
|---|---|---|---|
|Workflow-visible non-secret variables|`fabro-variable`|⚠️ via context only|Settings -> Variables; P2|
|Workflow-visible secret vault|`fabro-vault`|❌|Settings -> Secrets (write-only); P2|
|Centralized config types|`fabro-config`|⚠️ scattered|`project.toml` + config objects; P1-P2|
|project.toml / workflow.toml split|`fabro-config`|❌ (no TOML layer)|Build both; P1-P2 (**recommend splitting env config into project.toml**)|

### A.9 API, client and web UI

|Capability|Fabro crate(s)|Python today|Gap and target phase|
|---|---|---|---|
|REST API server|`fabro-server`, `fabro-api`|⚠️ ~9 Starlette routes, in-memory|FastAPI, ~30 resources; P2|
|Typed API client|`fabro-client`|❌|Optional generated client; P3|
|React/Vite web console|`apps/fabro-web`|❌|Operations Console; P2|
|Embedded SPA serving|`fabro-spa`, `fabro-static`|❌|Serve built SPA; P2|
|Install wizard / setup flow|`fabro-install`|❌|Optional; P3-P4|

### A.10 Automation and scheduling

|Capability|Fabro crate(s)|Python today|Gap and target phase|
|---|---|---|---|
|Scheduled / cron automations|`fabro-automation`|❌|Build; **P3-P4 [doc gap -- not mentioned]**|
|24/7 queued background runs|`fabro-server`|⚠️ runs are asyncio tasks, no queue/persistence|Durable run queue; P2|

### A.11 Infrastructure -- accounted, no Python analog required ➖

These Fabro crates are Rust-specific plumbing or internal tooling. They are
listed so the matrix accounts for **every** crate; none implies a Python
deliverable.

|Fabro crate|Why no analog|
|---|---|
|`build-support`, `fabro-macros`, `fabro-proc`|Rust build/proc-macro/process plumbing|
|`fabro-http`, `fabro-static`, `fabro-util`, `fabro-types`|Shared Rust HTTP/string/util/type libs (Python uses stdlib + pydantic)|
|`fabro-options-metadata`, `fabro-manifest` (partial)|Internal metadata models (folded into Python config objects)|
|`fabro-dev`, `fabro-test`, `fabro-dump`, `fabro-install` (dev parts)|Internal dev/test/diagnostic tooling|
|`fabro-cli`|Rust binary entrypoint; Python equivalent is `attractor_pipeline/cli.py` (✅ exists, to be extended)|

### Summary of doc gaps surfaced by the exercise

The matrix flags six capabilities the prose roadmap did not originally place,
all of which bear on the "walk-away safety + Fabro UX" this design adopts from
Fabro:

1. Git-worktree local isolation -- the original doc left local as raw host exec.
2. Git checkpointing -- the original doc deferred this to open decisions later;
   this revision pulls it into Phase 2.
3. Mid-turn steering API/UI -- engine plumbing exists, but it was not mentioned.
4. MCP client -- not mentioned.
5. Lifecycle hooks (`project.toml` post-tool-use) -- not mentioned.
6. Scheduled automations -- not mentioned.

Items 1 and 2 are the spine of Fabro's safety story and are pulled earlier than
the original draft because write-back, the Phase 2 milestone's final step,
transitively requires the isolation chain.

## Appendix B: Dependency-Ordered Build Sequence

Read top-to-bottom. Each item lists what it **needs** (↑) and what it
**unblocks** (→). Items in the same layer have no dependency on each other and
can be built in parallel. The **critical path** is marked ★ -- these gate the
most downstream work.

```text
────────────────────────────────────────────────────────────────────────
LAYER 0 -- Engine contracts (Phase 1, no new infra)
────────────────────────────────────────────────────────────────────────
0a ★ Config objects + error types + stable public APIs
      ↑ nothing   → everything below (typed surface to build on)
0b   Variable-expansion / lint parity audit
      ↑ nothing   → trustworthy validation before runs are durable
0c   RunSpec-as-manifest (immutable launch request)
      ↑ 0a        → durable runs (1a), API launch (3a)

────────────────────────────────────────────────────────────────────────
LAYER 1 -- Two independent spines (Phase 1→2). Build both in parallel.
────────────────────────────────────────────────────────────────────────
SPINE A -- Durability                       SPINE B -- Isolation
1a ★ RunRecord + RunEvent (Postgres)       1b ★ Git-worktree local sandbox
      ↑ 0a, 0c                                   ↑ 0a
      → history, SSE-durable, API, queue          → checkpointing, safe exec,
1a.1  Artifact store (fs interface)               write-back, PR
      ↑ 1a → artifact API, PR evidence       1b.1 RunEnvironment interface
1a.2  Redaction layer (centralized)               (local | docker | remote)
      ↑ 1a → safe event/log persistence            ↑ 1b → docker (2b), cloud (4)

────────────────────────────────────────────────────────────────────────
LAYER 2 -- Built on a spine (Phase 2)
────────────────────────────────────────────────────────────────────────
2a ★ Git checkpointing (per-stage commits to refs)
      ↑ 1b (worktree)        → resume/revert/trace, PR provenance
2b   Docker sandbox wired to RunEnvironment
      ↑ 1b.1                 → shared mutating runs default
2c   Durable run queue (24/7 background runs)
      ↑ 1a                   → automations (5b), capacity/health
2d   project.toml / workflow.toml + environment domain
      ↑ 0a, 1b.1             → per-repo env config, Settings→Environments
2e   Secret vault + variables (write-only secrets)
      ↑ 1a                   → credentialed runs, Settings→Secrets/Variables

────────────────────────────────────────────────────────────────────────
LAYER 3 -- Platform surface (Phase 2)
────────────────────────────────────────────────────────────────────────
3a ★ FastAPI surface (repos, workflows, runs, events, approvals,
       artifacts, cancel, settings, health, capacity)
      ↑ 1a, 1a.1, 0c, 2d     → React console, typed client
3b   SSE repointed to durable events
      ↑ 1a, 3a               → live console without losing history
3c   ApprovalDecision persistence
      ↑ 1a, 3a               → durable gates, write-back authorization

────────────────────────────────────────────────────────────────────────
LAYER 4 -- Console + safe apply (Phase 2 milestone = "trusted-LAN preview")
────────────────────────────────────────────────────────────────────────
4a ★ React/Vite Operations Console (Home, Runs, Approvals, Artifacts,
       Repos, Workflow Detail, Settings, System)
      ↑ 3a, 3b               → operator UX
4b   Write-back / apply-to-repo  ⚠ prefer branch-from-worktree over patch-apply
      ↑ 1b, 2a, 3c           → completes the preview rollout
4c   Steering API + steer-bar UI (engine plumbing already exists)
      ↑ 3a, 4a               → mid-turn intervention

  ▶ MILESTONE: register repo → discover → validate → run (local/docker)
    → stream+persist events → human gate → artifacts → approve → apply

────────────────────────────────────────────────────────────────────────
LAYER 5 -- Factory features (Phase 3)
────────────────────────────────────────────────────────────────────────
5a   GitHub auth + PR automation (branch → commit → PR + evidence)
      ↑ 2a (checkpoint), 1b (worktree), 1a.1 (artifacts)
5b   Scheduled automations (cron)
      ↑ 2c (durable queue), 3a
5c   MCP client (external tool servers)
      ↑ tools layer (✅), 3a → additive, no hard upstream dep
5d   Lifecycle hooks (project.toml post_tool_use)
      ↑ 2d (project.toml), tools layer (✅)
5e   Spec / work-order interview → run
      ↑ interviewer (✅), 3a, 4a

────────────────────────────────────────────────────────────────────────
LAYER 6 -- Control plane (Phase 4)
────────────────────────────────────────────────────────────────────────
6a   Cloud/remote sandbox (Daytona adapter)  ↑ 1b.1
6b   SSH / preview links                     ↑ 6a
6c   Object-native store (SlateDB adapter)   ↑ 1a (behind interface)
6d   Slack / tracker integrations            ↑ 3a, 5e
6e   Auth / roles / SSO / governance         ↑ actor_label hooks (everywhere)

────────────────────────────────────────────────────────────────────────
CRITICAL PATH (longest chain):
  0a → 1a → 3a → 4a → 4b
        └─ 1b → 2a → 4b      (isolation chain rejoins at write-back)
Everything else hangs off these. If you serialize, do 0a, then 1a‖1b,
then 2a‖2d, then 3a, then 4a, then 4b.
```

Three things worth pulling out of the diagram:

- The two Layer-1 spines, durability `1a` and isolation `1b`, are the whole
  game. They share no dependencies, so put one person/agent on each. Nearly
  everything downstream needs one or both. The original doc treated `1a`
  durability as foundational and let `1b`/`2a` drift to later; this sequence
  shows why that ordering is wrong. Write-back (`4b`), the Phase 2 milestone's
  final step, transitively requires the isolation chain (`1b → 2a`). Defer
  isolation and the preview either ships without safe apply or bolts worktrees on
  under deadline.
- Steering (`4c`), MCP (`5c`), and hooks (`5d`) are cheap re-attachments, not
  new spines. The engine already has the steer queue; tools already exist.
  They're late only because they need the API/console to be visible, not because
  they're hard. That helps the Fabro UX feel arrive sooner than their phase
  number suggests.
- `actor_label` is the one thing that must be threaded everywhere from day one:
  `RunSpec`, events, approvals, write-back. It is the only Layer-6 concern
  (`6e`, auth/SSO) that is not cheap to retrofit, which is why this design stubs
  it early.
