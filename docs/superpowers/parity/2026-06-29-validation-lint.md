# Validation and Lint Parity Audit

## Decision

Phase 1 keeps the existing Python validation rule surface and adds explicit tests for the rules most important to platform launch safety. The platform package treats validation errors as workflow package load failures, so invalid repo-local workflows cannot produce `RunSpec` manifests.

## Locked Python Behavior

- `R01` missing or duplicate start nodes are errors.
- `R02` missing or duplicate exit nodes are errors.
- `R03` incoming edges to the start node are errors.
- `R04` outgoing edges from exit nodes are errors.
- `R05` unreachable nodes are warnings.
- `R06` edges referencing missing nodes are errors.
- `R07` no reachable exit is an error.
- `R08` conditional nodes with fewer than two outgoing edges are warnings.
- `R09` goal gates without retry targets are warnings.
- `R10` missing retry targets are errors.
- `R11` self-loops are warnings.
- `R12` missing graph goal is info.
- `R13` box nodes without prompts are warnings.
- `R14` invalid edge condition syntax is an error.
- `R15` manager nodes without `child_graph` are errors.

## Phase 1 Rationale

The current Python validator already enforces the core StrongDM Attractor graph constraints and several hardening rules added during prior spec-compliance work. Phase 1 should make those rules visible and stable at the platform boundary before adding server-side workflow indexing and launch APIs.
