# Variable Expansion Parity Audit

## Decision

Phase 1 keeps the existing Python `$name` and `${name}` expansion semantics. The platform records the differences from Fabro's MiniJinja-style templating rather than changing prompt expansion during engine hardening.

## Locked Python Behavior

- `$name` expands when `name` exists in the context and the value is `str`, `int`, `float`, or `bool`.
- `${name}` expands with the same lookup behavior as `$name`.
- `\$name` emits a literal `$name`.
- Undefined variables are kept by default.
- Callers can request undefined variables to become an empty string.
- Callers can request undefined variables to raise `KeyError`.
- Dotted names such as `$service.name` are single context keys, not object traversal.
- Expansion is not recursive. If `$outer` maps to `$inner`, the output is `$inner`.
- Non-scalar values are not expanded.

## Phase 1 Rationale

Changing prompt interpolation semantics can alter existing workflows. Phase 1 is a hardening phase, so the safe behavior is to test and document the current Python semantics. A future templating change must be introduced behind an explicit config switch and migration notes.
