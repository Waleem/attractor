import {
  canCancelRunStatus,
  diffSummaryLabel,
  eventFromSseMessage,
  formatCompactRelativeTime,
  isWorkspaceCleanedDiffError,
  mergeRunEvents,
  runLane,
  runListAction,
  runMetaLine,
  runWorkflowName,
  shortRunId,
  summarizeRunDiff
} from "./runViewModel.js";

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
assertEqual(
  runWorkflowName(run({ run_spec: null, workflow_id: "wf_0123456789abcdef0123456789abcdef" })),
  "Workflow run",
  "hash-like workflow ids are not used as workflow labels"
);
assertEqual(
  runWorkflowName(run({ run_spec: null, workflow_id: "0123456789abcdef0123456789abcdef" })),
  "Workflow run",
  "bare digest workflow ids are not used as workflow labels"
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

assertEqual(canCancelRunStatus("queued"), true, "queued runs can be cancelled");
assertEqual(canCancelRunStatus("running"), true, "running runs can be cancelled");
assertEqual(canCancelRunStatus("waiting_for_approval"), true, "approval-waiting runs can be cancelled");
assertEqual(canCancelRunStatus("completed"), false, "completed runs cannot be cancelled");
assertEqual(canCancelRunStatus("failed"), false, "failed runs cannot be cancelled");

assertEqual(runListAction("running", true), "cancel", "cancelable list rows show cancel as their contextual action");
assertEqual(runListAction("completed", true), "rerun", "rerunnable terminal list rows show re-run");
assertEqual(runListAction("failed", false), "open", "non-rerunnable terminal list rows show open");

const summary = summarizeRunDiff({
  run_id: "run_1",
  base_commit: "base",
  head_commit: "head",
  truncated: false,
  files: [
    { path: "a.ts", status: "modified", additions: 7, deletions: 2 },
    { path: "b.ts", status: "added", additions: 3, deletions: 0 }
  ]
});
assertEqual(summary.status, "ready", "diff summary is ready for loaded diffs");
assertEqual(summary.files, 2, "diff summary counts changed files");
assertEqual(summary.additions, 10, "diff summary totals additions");
assertEqual(summary.deletions, 2, "diff summary totals deletions");
assertEqual(diffSummaryLabel(summary), "+10 -2 / 2 files", "diff label includes counts and file total");
assertEqual(
  diffSummaryLabel({ status: "pending" }),
  "Diff loading",
  "diff pending copy is clean and does not use stale placeholder language"
);
assertEqual(diffSummaryLabel({ status: "none" }), "No diff", "empty diff state is explicit");
assertEqual(
  diffSummaryLabel({ status: "unavailable" }),
  "Diff unavailable",
  "unavailable diff state is explicit"
);
assertEqual(
  isWorkspaceCleanedDiffError("Run does not have an owned worktree for diff"),
  true,
  "missing owned worktree errors are classified as cleaned workspace diff errors"
);
assertEqual(
  isWorkspaceCleanedDiffError("git diff failed because refs diverged"),
  false,
  "non-workspace diff errors still surface as errors"
);

assertEqual(
  formatCompactRelativeTime("2026-07-01T12:00:00Z", Date.parse("2026-07-03T12:00:00Z")),
  "2d ago",
  "old timestamps stay old in compact relative time"
);
assertEqual(
  formatCompactRelativeTime("2026-07-03T12:00:30Z", Date.parse("2026-07-03T12:00:00Z")),
  "30s from now",
  "future timestamps use from-now suffix"
);

const event = eventFromSseMessage(
  "stage.completed",
  {
    data: JSON.stringify({
      node_id: "build",
      actor_label: "worker",
      created_at: "2026-07-01T10:30:00Z"
    }),
    lastEventId: "42"
  },
  "2026-07-03T12:00:00Z"
);
assertEqual(event?.sequence, 42, "SSE event sequence comes from lastEventId");
assertEqual(event?.actor_label, "worker", "SSE event actor is preserved from payload");
assertEqual(
  event?.created_at,
  "2026-07-01T10:30:00Z",
  "SSE event created_at is preserved from payload instead of overwritten with receive time"
);

const metadataOnlyEvent = eventFromSseMessage(
  "stage.completed",
  {
    data: JSON.stringify({ node_id: "build" }),
    lastEventId: "43"
  },
  "2026-07-03T12:00:00Z"
);
assertEqual(
  metadataOnlyEvent?.created_at,
  null,
  "SSE events without durable created_at do not invent receive-time timestamps"
);
assertEqual(
  metadataOnlyEvent?.actor_label,
  "",
  "SSE events without durable actor metadata keep actor_label empty"
);

const mergedEvents = mergeRunEvents([
  {
    sequence: 43,
    event_type: "stage.completed",
    payload: { node_id: "build", output: "saved from durable store", commit_sha: "abc123" },
    actor_label: "durable-worker",
    created_at: "2026-07-01T10:30:00Z"
  },
  metadataOnlyEvent!
]);
assertEqual(mergedEvents.length, 1, "duplicate sequence events are merged");
assertEqual(
  mergedEvents[0]?.created_at,
  "2026-07-01T10:30:00Z",
  "durable created_at wins when later SSE replay lacks created_at"
);
assertEqual(
  mergedEvents[0]?.actor_label,
  "durable-worker",
  "durable actor_label wins when later SSE replay lacks actor_label"
);
assertEqual(
  mergedEvents[0]?.payload.output,
  "saved from durable store",
  "durable payload output survives when later SSE replay omits output"
);
assertEqual(
  mergedEvents[0]?.payload.commit_sha,
  "abc123",
  "durable payload commit_sha survives when later SSE replay omits commit_sha"
);
