interface RunSpecLike {
  workflow_name?: string;
  workflow?: string;
  actor_label?: string;
  requested_environment?:
    | string
    | {
        mode?: string;
        name?: string;
      };
}

interface RunLike {
  id?: string;
  status: string;
  workflow_id: string;
  run_spec: RunSpecLike | null;
  actor_label?: string;
  source_commit?: string | null;
  source_branch?: string | null;
}

export type RunLane = "queued" | "running" | "awaiting" | "done" | "failed";

export function shortRunId(runId: string | null | undefined): string {
  if (!runId) {
    return "None";
  }
  const normalized = runId.startsWith("run_") ? runId.slice(4) : runId;
  return normalized.length > 8 ? normalized.slice(0, 8) : normalized;
}

export function runWorkflowName(run: Pick<RunLike, "workflow_id" | "run_spec">): string {
  const workflowName = run.run_spec?.workflow_name ?? run.run_spec?.workflow;
  return workflowName || run.workflow_id || "Workflow";
}

export function runMetaLine(run: RunLike): string {
  const environment = requestedEnvironmentName(run.run_spec?.requested_environment);
  const parts = [
    run.actor_label || run.run_spec?.actor_label || "operator",
    run.source_branch || "no branch",
    shortSha(run.source_commit),
    environment || "default"
  ];
  return parts.filter(Boolean).join(" / ");
}

export function runLane(run: Pick<RunLike, "status">): RunLane {
  return laneForStatus(run.status);
}

export function laneForStatus(status: string): RunLane {
  if (["queued", "preparing"].includes(status)) {
    return "queued";
  }
  if (["running"].includes(status)) {
    return "running";
  }
  if (["waiting_for_approval"].includes(status)) {
    return "awaiting";
  }
  if (["completed", "cancelled", "writeback_pending", "writeback_applied"].includes(status)) {
    return "done";
  }
  return "failed";
}

export function isTerminalRunStatus(status: string): boolean {
  return ["completed", "failed", "cancelled", "writeback_applied", "writeback_failed"].includes(status);
}

function requestedEnvironmentName(value: RunSpecLike["requested_environment"]): string {
  if (!value) {
    return "";
  }
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "object") {
    return value.name ?? value.mode ?? "";
  }
  return "";
}

function shortSha(value: string | null | undefined): string {
  if (!value) {
    return "None";
  }
  return value.length > 12 ? value.slice(0, 12) : value;
}
