import { runLane, runMetaLine, runWorkflowName, shortRunId } from "./runViewModel.js";

function assertEqual(actual: unknown, expected: unknown, message: string) {
  if (actual !== expected) {
    throw new Error(`${message}\nexpected: ${String(expected)}\nactual:   ${String(actual)}`);
  }
}

interface TestRun {
  id: string;
  status: string;
  repo_id: string;
  workflow_id: string;
  run_spec: {
    workflow_name?: string;
    workflow?: string;
    repo_path?: string;
    actor_label?: string;
    requested_environment?: string;
  } | null;
  actor_label: string;
  source_commit: string;
  source_branch: string;
  worktree_path: string | null;
  managed_branch: string | null;
  error_category: string | null;
  error_message: string | null;
  created_at: string | null;
  updated_at: string | null;
  started_at: string | null;
  completed_at: string | null;
}

function run(overrides: Partial<TestRun> = {}): TestRun {
  return {
    id: "run_0123456789abcdef",
    status: "queued",
    repo_id: "repo_1",
    workflow_id: "workflow_release",
    run_spec: {
      workflow_name: "release",
      workflow: "legacy-release",
      repo_path: "/workspace/project",
      actor_label: "operator",
      requested_environment: "local"
    },
    actor_label: "operator",
    source_commit: "abcdef1234567890",
    source_branch: "main",
    worktree_path: null,
    managed_branch: null,
    error_category: null,
    error_message: null,
    created_at: "2026-07-03T12:00:00Z",
    updated_at: "2026-07-03T12:01:00Z",
    started_at: null,
    completed_at: null,
    ...overrides
  };
}

assertEqual(runWorkflowName(run()), "release", "workflow_name is the primary label");
assertEqual(
  runWorkflowName(run({ run_spec: { workflow: "fallback-workflow" } })),
  "fallback-workflow",
  "legacy workflow field is used when workflow_name is missing"
);
assertEqual(
  runWorkflowName(run({ run_spec: null, workflow_id: "workflow_fallback" })),
  "workflow_fallback",
  "workflow_id is the final workflow label fallback"
);

assertEqual(shortRunId("run_0123456789abcdef"), "01234567", "run_ prefix is removed before shortening");
assertEqual(shortRunId("abc123"), "abc123", "short ids are left intact");

assertEqual(runLane(run({ status: "queued" })), "queued", "queued runs map to the queued lane");
assertEqual(runLane(run({ status: "preparing" })), "queued", "preparing runs map to queued");
assertEqual(runLane(run({ status: "running" })), "running", "running runs map to running");
assertEqual(runLane(run({ status: "waiting_for_approval" })), "awaiting", "approval waits map to awaiting");
assertEqual(runLane(run({ status: "completed" })), "done", "completed runs map to done");
assertEqual(runLane(run({ status: "cancelled" })), "done", "cancelled runs map to done");
assertEqual(runLane(run({ status: "writeback_pending" })), "done", "writeback pending maps to done");
assertEqual(runLane(run({ status: "writeback_applied" })), "done", "applied writeback maps to done");
assertEqual(runLane(run({ status: "failed" })), "failed", "failed runs do not map to a board lane");
assertEqual(runLane(run({ status: "writeback_failed" })), "failed", "writeback failed stays behind the failed filter");

assertEqual(
  runMetaLine(run()),
  "operator / main / abcdef123456 / local",
  "meta line includes actor, branch, source commit, and environment"
);
