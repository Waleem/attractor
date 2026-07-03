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
export type RunListAction = "cancel" | "rerun" | "open";

export interface RunDiffLike {
  run_id?: string;
  base_commit?: string;
  head_commit?: string;
  truncated?: boolean;
  files: Array<{
    path?: string;
    status?: string;
    additions: number;
    deletions: number;
    patch?: string;
    patch_truncated?: boolean;
  }>;
}

export type RunDiffSummary =
  | {
      status: "ready";
      files: number;
      additions: number;
      deletions: number;
    }
  | { status: "pending" }
  | { status: "deferred" }
  | { status: "none" }
  | { status: "unavailable" };

export interface SseMessageLike {
  data: string;
  lastEventId: string;
}

export function shortRunId(runId: string | null | undefined): string {
  if (!runId) {
    return "None";
  }
  const normalized = runId.startsWith("run_") ? runId.slice(4) : runId;
  return normalized.length > 8 ? normalized.slice(0, 8) : normalized;
}

export function runWorkflowName(run: Pick<RunLike, "workflow_id" | "run_spec">): string {
  const workflowName = run.run_spec?.workflow_name ?? run.run_spec?.workflow;
  if (workflowName) {
    return workflowName;
  }
  if (run.workflow_id && !isHashLikeWorkflowId(run.workflow_id)) {
    return run.workflow_id;
  }
  return "Workflow run";
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

export function canCancelRunStatus(status: string): boolean {
  return ["queued", "preparing", "running", "waiting_for_approval"].includes(status);
}

export function runListAction(status: string, canRerun: boolean): RunListAction {
  if (canCancelRunStatus(status)) {
    return "cancel";
  }
  return canRerun ? "rerun" : "open";
}

export function summarizeRunDiff(diff: RunDiffLike): Extract<RunDiffSummary, { status: "ready" }> {
  return diff.files.reduce<Extract<RunDiffSummary, { status: "ready" }>>(
    (summary, file) => ({
      status: "ready",
      files: summary.files + 1,
      additions: summary.additions + file.additions,
      deletions: summary.deletions + file.deletions
    }),
    { status: "ready", files: 0, additions: 0, deletions: 0 } as Extract<RunDiffSummary, { status: "ready" }>
  );
}

export function diffSummaryLabel(summary: RunDiffSummary): string {
  switch (summary.status) {
    case "ready":
      if (summary.files === 0) {
        return "No diff";
      }
      return `+${summary.additions} -${summary.deletions} / ${summary.files} ${summary.files === 1 ? "file" : "files"}`;
    case "pending":
      return "Diff loading";
    case "deferred":
      return "Diff after run";
    case "none":
      return "No diff";
    case "unavailable":
      return "Diff unavailable";
  }
}

export function formatCompactRelativeTime(value: string | null | undefined, now = Date.now()): string {
  if (!value) {
    return "No timestamp";
  }
  const date = new Date(value);
  const delta = now - date.valueOf();
  if (Number.isNaN(delta)) {
    return value;
  }
  const abs = Math.abs(delta);
  const suffix = delta >= 0 ? "ago" : "from now";
  const units: Array<[number, string]> = [
    [86_400_000, "d"],
    [3_600_000, "h"],
    [60_000, "m"],
    [1_000, "s"]
  ];
  for (const [size, label] of units) {
    if (abs >= size) {
      return `${Math.round(abs / size)}${label} ${suffix}`;
    }
  }
  return "now";
}

export function eventFromSseMessage(
  eventType: string,
  message: SseMessageLike,
  receivedAt = new Date().toISOString()
) {
  let payload: Record<string, unknown> = {};
  try {
    const parsed = JSON.parse(message.data) as unknown;
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      payload = parsed as Record<string, unknown>;
    }
  } catch {
    payload = { message: message.data };
  }

  const sequence = Number(message.lastEventId);
  if (!Number.isFinite(sequence)) {
    return null;
  }

  return {
    sequence,
    event_type: eventType,
    payload,
    actor_label: stringPayload(payload, "actor_label") ?? "",
    created_at: stringPayload(payload, "created_at") ?? receivedAt
  };
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

function isHashLikeWorkflowId(value: string): boolean {
  return /^(?:wf_)?[a-f0-9]{32,64}$/i.test(value);
}

function stringPayload(payload: Record<string, unknown>, key: string): string | null {
  const value = payload[key];
  return typeof value === "string" && value.length > 0 ? value : null;
}
