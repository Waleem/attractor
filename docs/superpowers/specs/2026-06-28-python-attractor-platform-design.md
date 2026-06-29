# Python Attractor Platform Design

## Summary

This design describes a phased product direction for extending the existing Python
Attractor implementation into a small-team workflow operations platform. The
platform keeps the workflow engine, execution runtime, API server, persistence,
sandboxing, and workflow-control logic Python-based, while allowing a React/Vite
frontend for the web console.

The product adopts Fabro-style local workflow and operations conventions where
they fit the Python implementation: repo-local workflow packages, local execution
as a first-class mode, Docker sandbox execution for shared mutating runs, durable
run history, approvals, artifacts, and an operations-oriented GUI. It does not
attempt Fabro feature parity in the first release. Instead, it builds a foundation
that can later support cloud sandboxes, SSH/preview links, Git checkpointing,
natural-language specs, PR automation, and broader SDLC control-plane features.

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

### Phase 1: Polish the Python Attractor Engine

Phase 1 stabilizes the current Python engine around the contracts needed by the
shared platform. This is targeted product-oriented hardening, not generic
refactoring.

Phase 1 work is sequenced in three waves:

1. API cleanup and correctness: fix naming/spec mismatches, stabilize public
   Python APIs, define config objects, error types, docs, and compatibility
   tests.
2. Runtime reliability: harden cancellation, retries, timeouts, event ordering,
   checkpoint/resume behavior, durable run state hooks, execution environment
   lifecycle, and artifact capture.
3. Developer ergonomics: improve CLI behavior, workflow validation, example
   workflows, template generation, workflow TOML support, and logs.

The existing local pipeline execution capability remains first-class. Phase 1
must not force Docker on the CLI or library APIs.

### Phase 2: Add a Fabro-Like GUI and Shared Server

Phase 2 introduces a FastAPI backend and React/Vite Operations Console. The
server runs on a single trusted-LAN host, indexes local repo paths, records run
history in Postgres, stores artifacts on the filesystem or object storage, and
uses Docker by default for shared mutating workflows.

The GUI center of gravity is an Operations Console: active runs, queued runs,
approvals, queue health, failures, artifacts, write-back review, and system
settings. Repo catalog and graph inspection are supporting views rather than the
home screen.

### Phase 3: Add Factory Features

Phase 3 builds factory features on top of the reliable runner in this order:

1. Spec and work-order generation: interview a human, create repo-local specs or
   work orders, and run workflows against them.
2. PR automation: approved sandbox changes become branches, commits, and pull
   requests with summaries and test evidence.
3. Review and repair loops: automated code review, test failure triage, and
   iterative repair workflows.

### Phase 4: Add Control-Plane Capabilities

Phase 4 expands toward an SDLC control plane: organization-wide traceability,
governance, living requirements, decision history, cross-repo visibility,
policy, roles, SSO, cloud or remote sandbox adapters, and deeper SDLC reporting.

## Repo Workflow Layout

The canonical repo-local workflow layout is:

```text
.attractor/
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

`workflow.dot` is required and remains the executable Attractor graph.
`workflow.toml` is optional. If TOML is absent, the server infers the workflow
name from the directory and applies platform defaults.

`workflow.toml` owns operational metadata and platform configuration, such as:

- display name and description
- tags
- required inputs
- default provider and model
- execution environment request
- Docker image or server-managed environment reference
- approval policy
- write-back policy
- artifact paths
- retention policy

The DOT graph should remain focused on workflow control flow and prompts.
Operational configuration should move to TOML when it affects the platform rather
than the graph semantics.

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
- discovered workflow packages

Phase 1 and Phase 2 support local path registration only. Git remote registration
is a later extension.

### WorkflowPackage

`WorkflowPackage` represents a discovered workflow under
`.attractor/workflows/<name>/`. It records:

- repo id
- workflow name
- DOT path
- optional TOML path
- parsed TOML config
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
- retention policy
- approval policy
- write-back policy

Runs are pinned to the recorded source commit. If the registered repo moves
before write-back, write-back must fail until the operator resolves the mismatch.

### ExecutionRun and RunEnvironment

`ExecutionRun` is the runtime instance of a workflow execution. It uses a
`RunEnvironment` behind a stable interface:

```text
RunEnvironment
  local   -> direct host execution, used by CLI/dev/trusted workflows
  docker  -> local Docker sandbox per run, default for shared mutating workflows
  remote  -> future cloud VM or remote sandbox adapter
```

Local execution remains first-class for the Python engine and CLI. The shared
server defaults to Docker for workflows that can mutate code. Workflow TOML may
request an environment, but server policy can enforce a stricter environment.

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

`WriteBackPlan` represents approved application of sandbox changes back to the
registered local repo path. It is created only after a run produces changes and a
human approves write-back.

Write-back must refuse to apply changes when:

- the registered repo path is missing
- the registered worktree is dirty
- the registered repo is no longer at the run's recorded base commit
- the patch does not apply cleanly
- filesystem permissions prevent the write

The initial platform write-back path applies approved changes back to the
registered local repo. Branch and PR automation waits for Phase 3.

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
- write-back errors: base commit changed, local repo dirty, patch conflict, or
  filesystem permission failure

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
/api/repos/{repo_id}/workflows
/api/workflows/{workflow_id}/validate
/api/runs
/api/runs/{run_id}
/api/runs/{run_id}/events
/api/runs/{run_id}/approvals
/api/runs/{run_id}/artifacts
/api/runs/{run_id}/cancel
/api/runs/{run_id}/writeback
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

## React Operations Console

The Phase 2 GUI is a React/Vite application. It is not server-rendered and does
not need to be Python-based. Its job is to make the shared workflow server easy
to operate.

Primary screens:

- Home: active runs, queued runs, waiting approvals, recent failures, Docker
  capacity, and retention warnings
- Runs: run list and run detail with timeline, graph/node status, logs, model
  and tool activity, errors, and cancellation
- Approvals: pending human gates and write-back approvals
- Artifacts: patch and diff viewer, generated files, test output, summaries,
  retained bundles, and approved apply-to-repo action
- Repos: registered local paths, Git commit, dirty-state status, index status,
  and discovered workflow packages
- Workflow Detail: DOT validation, optional TOML metadata, required inputs,
  default environment, retention, approval/write-back policy, and launch form
- Settings: operational admin area
- System: health and capacity summary

The Settings area includes:

- Models: LLM providers, default models, and credential status
- Integrations: GitHub, Slack, webhooks, and future service connections
- Sandboxes: execution backends, including local, Docker, and future remote
  environments
- Environments: server-managed runtime definitions and Docker images
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
records. It stores repos, workflow package metadata, run records, run events,
approval decisions, artifact metadata, settings, and write-back records.

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
- shared mutating workflows default to Docker
- secrets are write-only from the GUI perspective
- write-back checks base commit and clean worktree state before applying changes
- unsafe artifacts and oversize artifacts are handled by retention policy
- server settings should make the current no-auth posture explicit

Roles, SSO, organization governance, and policy enforcement beyond these
guardrails are Phase 4 work.

## Testing

Phase 1 tests:

- contract tests for `RunEnvironment` across local and Docker
- workflow package loader tests for required DOT and optional TOML
- durable event model tests for ordering, replay, state transitions, and SSE
  projection
- artifact tests for patches, logs, summaries, retained workspace bundles, and
  retention cleanup
- write-back tests for clean apply, dirty repo rejection, base commit mismatch,
  and patch conflict
- regression tests for existing local CLI and library behavior

Phase 2 tests:

- FastAPI API tests for repos, workflows, runs, events, approvals, artifacts,
  cancellation, write-back, settings, health, and capacity
- Postgres integration tests for run records, event append/replay, and artifact
  metadata
- Docker integration tests for actual per-run workspaces
- React route and component tests for Home, Runs, Approvals, Artifacts, Repos,
  Workflow Detail, Settings, and System
- end-to-end tests for register repo, index workflow, launch run, approve gate,
  inspect artifacts, and apply write-back

## Rollout

The first usable milestone is a trusted-LAN preview that can:

1. register a local repo path
2. discover `.attractor` workflow packages
3. validate a workflow
4. launch a run using local or Docker execution
5. stream and persist durable events
6. pause for a human gate
7. capture artifacts
8. approve write-back
9. safely apply changes back to a clean registered repo

The preview should favor boring completeness over breadth. It should not include
PR automation, cloud sandboxes, SSO, Git remote repo management, or natural
language work-order generation. Those features build on the stable runner in
later phases.

## Open Design Decisions For Later

These decisions are intentionally deferred:

- whether cloud sandboxing uses remote Docker hosts, VMs, or a third-party
  sandbox service
- whether Git checkpointing is implemented per node, per stage, or per run
- whether PR automation uses local Git commands, GitHub API integration, or both
- whether SlateDB becomes useful for object-native event or artifact storage
- how the control plane models cross-repo requirements, decisions, and policies
- when to introduce local users, roles, and SSO
