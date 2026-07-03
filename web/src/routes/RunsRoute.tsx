import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import {
  answerApproval,
  cancelRun,
  getRunDiff,
  launchRun,
  listApprovals,
  listRepos,
  listRuns,
  listWorkflows,
  runSpecToLaunchInput,
  type ApprovalDecision,
  type RunDiff,
  type RunRecord,
  type Workflow
} from "../api";
import { useRunEvents } from "../hooks/useRunEvents";
import { isTerminalRunStatus, runLane, runMetaLine, runWorkflowName, shortRunId, type RunLane } from "../runViewModel";
import { useAsync } from "../components/useAsync";
import { CopyButton, EmptyState, ErrorBanner, Field, Loading, PageHeader, Panel, StatusBadge, StatusDot, formatDate } from "../components/ui";

type ViewMode = "list" | "board";
type StatusFilter = "all" | "active" | "queued" | "running" | "waiting_for_approval" | "completed" | "failed";

const statusFilters: Array<{ value: StatusFilter; label: string }> = [
  { value: "all", label: "All" },
  { value: "active", label: "Active" },
  { value: "queued", label: "Queued" },
  { value: "running", label: "Running" },
  { value: "waiting_for_approval", label: "Awaiting you" },
  { value: "completed", label: "Done" },
  { value: "failed", label: "Failed" }
];

const boardLanes: Array<{ value: Exclude<RunLane, "failed">; label: string }> = [
  { value: "queued", label: "Queued" },
  { value: "running", label: "Running" },
  { value: "awaiting", label: "Awaiting you" },
  { value: "done", label: "Done" }
];

export function RunsRoute({ navigate }: { navigate: (path: string) => void }) {
  const [viewMode, setViewMode] = useState<ViewMode>("list");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [repoFilter, setRepoFilter] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const runsState = useAsync(() => listRuns({ repo_id: repoFilter }), [repoFilter]);
  const reposState = useAsync(listRepos, []);
  const [selectedRepoId, setSelectedRepoId] = useState("");
  const selectedRepo = reposState.data?.find((repo) => repo.id === selectedRepoId) ?? null;
  const workflowsState = useAsync(
    () => (selectedRepoId ? listWorkflows(selectedRepoId) : Promise.resolve([])),
    [selectedRepoId]
  );
  const workflows = workflowsState.data ?? [];
  const [workflowName, setWorkflowName] = useState("");
  const [actorLabel, setActorLabel] = useState("operator");
  const [requestedEnvironment, setRequestedEnvironment] = useState("");
  const [inputKey, setInputKey] = useState("");
  const [inputValue, setInputValue] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [busyRunId, setBusyRunId] = useState<string | null>(null);
  const [launching, setLaunching] = useState(false);
  const [approvalRefreshToken, setApprovalRefreshToken] = useState(0);
  const [diffSummaries, setDiffSummaries] = useState<Record<string, RunDiffSummary>>({});
  const [connectedCount, setConnectedCount] = useState(0);
  const liveRefreshTimer = useRef<number | null>(null);
  const diffRequestsInFlight = useRef<Set<string>>(new Set());
  const mounted = useRef(true);
  const selectedWorkflow = useMemo(
    () => workflows.find((workflow) => workflow.name === workflowName) ?? workflows[0] ?? null,
    [workflowName, workflows]
  );
  const runs = useMemo(
    () => (runsState.data ?? []).slice().sort((a, b) => String(b.created_at ?? "").localeCompare(String(a.created_at ?? ""))),
    [runsState.data]
  );
  const filteredRuns = useMemo(
    () => runs.filter((run) => matchesStatus(run, statusFilter) && matchesSearch(run, searchQuery)),
    [runs, searchQuery, statusFilter]
  );
  const visibleActiveRuns = filteredRuns.filter((run) => !isTerminalRunStatus(run.status));
  const waitingRunIds = runs
    .filter((run) => run.status === "waiting_for_approval")
    .map((run) => run.id)
    .sort()
    .join(",");
  const approvalsState = useAsync<Record<string, ApprovalDecision[]>>(async () => {
    const waitingRuns = runs.filter((run) => run.status === "waiting_for_approval");
    const entries = await Promise.all(waitingRuns.map(async (run) => [run.id, await listApprovals(run.id)] as const));
    return Object.fromEntries(entries);
  }, [waitingRunIds, approvalRefreshToken]);
  const handleLiveEvent = useCallback(() => {
    if (liveRefreshTimer.current !== null) {
      return;
    }
    liveRefreshTimer.current = window.setTimeout(() => {
      liveRefreshTimer.current = null;
      runsState.refresh();
      setApprovalRefreshToken((value) => value + 1);
    }, 500);
  }, [runsState.refresh]);

  useEffect(() => {
    return () => {
      mounted.current = false;
      if (liveRefreshTimer.current !== null) {
        window.clearTimeout(liveRefreshTimer.current);
      }
    };
  }, []);

  useEffect(() => {
    if (!selectedRepoId && reposState.data && reposState.data.length > 0) {
      setSelectedRepoId(reposState.data[0].id);
    }
  }, [reposState.data, selectedRepoId]);

  useEffect(() => {
    if (workflows.length > 0 && !workflows.some((workflow) => workflow.name === workflowName)) {
      setWorkflowName(workflows[0].name);
    }
  }, [workflowName, workflows]);

  useEffect(() => {
    const candidates = filteredRuns.filter(
      (run) =>
        isTerminalRunStatus(run.status) &&
        run.managed_branch &&
        !diffSummaries[run.id] &&
        !diffRequestsInFlight.current.has(run.id)
    );
    for (const run of candidates) {
      diffRequestsInFlight.current.add(run.id);
      getRunDiff(run.id)
        .then((diff) => {
          if (!mounted.current) {
            return;
          }
          setDiffSummaries((current) => ({ ...current, [run.id]: summarizeDiff(diff) }));
        })
        .catch(() => {
          if (!mounted.current) {
            return;
          }
          setDiffSummaries((current) => ({ ...current, [run.id]: { status: "unavailable" } }));
        })
        .finally(() => {
          diffRequestsInFlight.current.delete(run.id);
        });
    }
  }, [diffSummaries, filteredRuns]);

  async function submitLaunch(event: FormEvent) {
    event.preventDefault();
    if (!selectedRepo || !selectedWorkflow) {
      setActionError("Select a repo and workflow before launching.");
      return;
    }
    setLaunching(true);
    setActionError(null);
    setActionMessage(null);
    try {
      const inputs = inputKey ? { [inputKey]: inputValue } : {};
      const run = await launchRun({
        repo_path: selectedRepo.local_path,
        workflow_name: selectedWorkflow.name,
        actor_label: actorLabel,
        inputs,
        requested_environment: requestedEnvironment
      });
      setActionMessage(`Launched ${run.id}`);
      runsState.refresh();
      navigate(`/runs/${run.id}`);
    } catch (caught) {
      setActionError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setLaunching(false);
    }
  }

  async function cancel(run: RunRecord) {
    setBusyRunId(run.id);
    setActionError(null);
    setActionMessage(null);
    try {
      const result = await cancelRun(run.id);
      setActionMessage(`${run.id}: ${result.status}`);
      runsState.refresh();
    } catch (caught) {
      setActionError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusyRunId(null);
    }
  }

  async function rerun(run: RunRecord) {
    const input = runSpecToLaunchInput(run.run_spec);
    if (!input) {
      setActionError(`Run ${run.id} does not include enough run_spec metadata to re-run.`);
      return;
    }
    setBusyRunId(run.id);
    setActionError(null);
    setActionMessage(null);
    try {
      const nextRun = await launchRun(input);
      setActionMessage(`Re-ran ${run.id} as ${nextRun.id}`);
      runsState.refresh();
      navigate(`/runs/${nextRun.id}`);
    } catch (caught) {
      setActionError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusyRunId(null);
    }
  }

  async function approveRun(run: RunRecord) {
    const pending = (approvalsState.data?.[run.id] ?? []).find((approval) => approval.status === "pending");
    if (!pending) {
      navigate(`/runs/${run.id}`);
      return;
    }
    setBusyRunId(run.id);
    setActionError(null);
    setActionMessage(null);
    try {
      await answerApproval(run.id, pending.id, { answer: "approve", actor_label: actorLabel || "operator" });
      setActionMessage(`Approved ${shortRunId(run.id)}`);
      setApprovalRefreshToken((value) => value + 1);
      runsState.refresh();
    } catch (caught) {
      setActionError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusyRunId(null);
    }
  }

  return (
    <>
      <PageHeader
        title="Runs"
        eyebrow={`${filteredRuns.length} shown`}
        actions={
          <a className="button-link" href="#launch-run">
            Launch
          </a>
        }
      />
      <ErrorBanner message={runsState.error ?? reposState.error ?? workflowsState.error ?? approvalsState.error ?? actionError} />
      {actionMessage ? <div className="notice">{actionMessage}</div> : null}
      <Panel title="Launch Run">
        <div id="launch-run" />
        {reposState.loading ? <Loading label="Loading repos" /> : null}
        <form className="launch-form run-launch-form" onSubmit={submitLaunch}>
          <Field label="Repo">
            <select value={selectedRepoId} onChange={(event) => setSelectedRepoId(event.target.value)} required>
              {reposState.data?.length ? null : <option value="">No repos</option>}
              {(reposState.data ?? []).map((repo) => (
                <option key={repo.id} value={repo.id}>
                  {repo.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Workflow">
            <select value={workflowName} onChange={(event) => setWorkflowName(event.target.value)} required>
              {workflows.length ? null : <option value="">No workflows</option>}
              {workflows.map((workflow) => (
                <option key={workflow.id} value={workflow.name}>
                  {workflow.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Actor">
            <input value={actorLabel} onChange={(event) => setActorLabel(event.target.value)} required />
          </Field>
          <Field label="Environment">
            <input value={requestedEnvironment} onChange={(event) => setRequestedEnvironment(event.target.value)} placeholder="local" />
          </Field>
          <Field label="Input key">
            <input value={inputKey} onChange={(event) => setInputKey(event.target.value)} />
          </Field>
          <Field label="Input value">
            <input value={inputValue} onChange={(event) => setInputValue(event.target.value)} disabled={!inputKey} />
          </Field>
          <button type="submit" className="primary-action" disabled={launching || !selectedRepo || !selectedWorkflow}>
            {launching ? "Launching" : "Launch"}
          </button>
        </form>
        <ValidationDiagnostics workflow={selectedWorkflow} />
      </Panel>
      <Panel title="Runs" actions={<LiveIndicator connectedCount={connectedCount} activeCount={visibleActiveRuns.length} />}>
        <LiveRunStreams runs={visibleActiveRuns} onEvent={handleLiveEvent} onConnectedCount={setConnectedCount} />
        <div className="runs-toolbar">
          <div className="segmented-control" role="group" aria-label="Run view">
            <button type="button" className={viewMode === "list" ? "active" : "secondary"} onClick={() => setViewMode("list")}>
              List
            </button>
            <button type="button" className={viewMode === "board" ? "active" : "secondary"} onClick={() => setViewMode("board")}>
              Board
            </button>
          </div>
          <Field label="Search">
            <input value={searchQuery} onChange={(event) => setSearchQuery(event.target.value)} placeholder="Run, workflow, actor, branch" />
          </Field>
          <Field label="Repo">
            <select value={repoFilter} onChange={(event) => setRepoFilter(event.target.value)}>
              <option value="">All repos</option>
              {(reposState.data ?? []).map((repo) => (
                <option key={repo.id} value={repo.id}>
                  {repo.name}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <div className="status-chip-row" role="group" aria-label="Status filter">
          {statusFilters.map((filter) => (
            <button
              key={filter.value}
              type="button"
              className={`status-chip ${statusFilter === filter.value ? "active" : ""}`}
              aria-pressed={statusFilter === filter.value}
              onClick={() => setStatusFilter(filter.value)}
            >
              {filter.label}
            </button>
          ))}
        </div>
        {runsState.loading ? <Loading /> : null}
        {filteredRuns.length === 0 && !runsState.loading ? (
          <EmptyRunState onLaunch={() => document.getElementById("launch-run")?.scrollIntoView({ behavior: "smooth", block: "start" })} />
        ) : viewMode === "list" ? (
          <RunList
            runs={filteredRuns}
            diffSummaries={diffSummaries}
            busyRunId={busyRunId}
            navigate={navigate}
            onCancel={cancel}
            onRerun={rerun}
          />
        ) : (
          <RunBoard
            runs={filteredRuns}
            showFailed={statusFilter === "failed"}
            approvals={approvalsState.data ?? {}}
            diffSummaries={diffSummaries}
            busyRunId={busyRunId}
            navigate={navigate}
            onApprove={approveRun}
          />
        )}
      </Panel>
    </>
  );
}

function LiveRunStreams({
  runs,
  onEvent,
  onConnectedCount
}: {
  runs: RunRecord[];
  onEvent: () => void;
  onConnectedCount: (count: number) => void;
}) {
  const [connectedIds, setConnectedIds] = useState<Set<string>>(new Set());
  const handleConnected = useCallback((runId: string, connected: boolean) => {
    setConnectedIds((current) => {
      const next = new Set(current);
      if (connected) {
        next.add(runId);
      } else {
        next.delete(runId);
      }
      return next;
    });
  }, []);

  useEffect(() => {
    onConnectedCount(connectedIds.size);
  }, [connectedIds.size, onConnectedCount]);

  return (
    <>
      {runs.map((run) => (
        <RunStreamSubscription key={run.id} runId={run.id} onEvent={onEvent} onConnected={handleConnected} />
      ))}
    </>
  );
}

function RunStreamSubscription({
  runId,
  onEvent,
  onConnected
}: {
  runId: string;
  onEvent: () => void;
  onConnected: (runId: string, connected: boolean) => void;
}) {
  const handleEvent = useCallback(() => onEvent(), [onEvent]);
  const stream = useRunEvents({ runId, onEvent: handleEvent });
  useEffect(() => {
    onConnected(runId, stream.connected);
    return () => onConnected(runId, false);
  }, [onConnected, runId, stream.connected]);
  return null;
}

function LiveIndicator({ connectedCount, activeCount }: { connectedCount: number; activeCount: number }) {
  return (
    <div className="live-indicator" aria-live="polite">
      <span className={`live-dot ${connectedCount > 0 || activeCount === 0 ? "connected" : ""}`} aria-hidden="true" />
      <span>{activeCount === 0 ? "Live idle" : connectedCount > 0 ? `Live ${connectedCount}/${activeCount}` : "Connecting"}</span>
    </div>
  );
}

function RunList({
  runs,
  diffSummaries,
  busyRunId,
  navigate,
  onCancel,
  onRerun
}: {
  runs: RunRecord[];
  diffSummaries: Record<string, RunDiffSummary>;
  busyRunId: string | null;
  navigate: (path: string) => void;
  onCancel: (run: RunRecord) => void;
  onRerun: (run: RunRecord) => void;
}) {
  return (
    <div className="run-list" role="list">
      {runs.map((run) => (
        <div key={run.id} className="run-row" role="listitem">
          <button type="button" className="run-row-open" onClick={() => navigate(`/runs/${run.id}`)}>
            <span className="run-row-status">
              <StatusDot status={run.status} />
              <span className="sr-only">{run.status}</span>
            </span>
            <span className="run-row-main">
              <strong>{runWorkflowName(run)}</strong>
              <span className="subtle">{runMetaLine(run)}</span>
            </span>
            <span className="run-row-pill">
              <StatusBadge status={run.status} />
            </span>
            <span className="run-row-time" title={formatDate(run.updated_at)}>
              {relativeTime(run.updated_at)}
            </span>
            <DiffSummaryView summary={diffSummaries[run.id]} />
          </button>
          <span className="run-id-copy">
            <span className="mono">{shortRunId(run.id)}</span>
            <CopyButton value={run.id} label="Copy run id" />
          </span>
          <span className="run-row-actions">
            <button type="button" className="secondary" disabled={!canCancel(run.status) || busyRunId === run.id} onClick={() => onCancel(run)}>
              Cancel
            </button>
            <button type="button" className="secondary" disabled={busyRunId === run.id} onClick={() => onRerun(run)}>
              Re-run
            </button>
          </span>
        </div>
      ))}
    </div>
  );
}

function RunBoard({
  runs,
  showFailed,
  approvals,
  diffSummaries,
  busyRunId,
  navigate,
  onApprove
}: {
  runs: RunRecord[];
  showFailed: boolean;
  approvals: Record<string, ApprovalDecision[]>;
  diffSummaries: Record<string, RunDiffSummary>;
  busyRunId: string | null;
  navigate: (path: string) => void;
  onApprove: (run: RunRecord) => void;
}) {
  const failedRuns = showFailed ? runs.filter((run) => runLane(run) === "failed") : [];
  return (
    <>
      <div className="run-board">
        {boardLanes.map((lane) => {
          const laneRuns = runs.filter((run) => runLane(run) === lane.value);
          return (
            <section key={lane.value} className="run-lane" aria-labelledby={`run-lane-${lane.value}`}>
              <h3 id={`run-lane-${lane.value}`}>{lane.label}</h3>
              <div className="run-card-stack">
                {laneRuns.length === 0 ? <div className="lane-empty">No runs</div> : null}
                {laneRuns.map((run) => (
                  <RunCard
                    key={run.id}
                    run={run}
                    approval={approvals[run.id]?.find((item) => item.status === "pending") ?? null}
                    diffSummary={diffSummaries[run.id]}
                    busy={busyRunId === run.id}
                    navigate={navigate}
                    onApprove={onApprove}
                  />
                ))}
              </div>
            </section>
          );
        })}
      </div>
      {failedRuns.length > 0 ? (
        <div className="failed-filter-results" aria-label="Failed filtered runs">
          {failedRuns.map((run) => (
            <RunCard
              key={run.id}
              run={run}
              approval={null}
              diffSummary={diffSummaries[run.id]}
              busy={busyRunId === run.id}
              navigate={navigate}
              onApprove={onApprove}
            />
          ))}
        </div>
      ) : null}
    </>
  );
}

function RunCard({
  run,
  approval,
  diffSummary,
  busy,
  navigate,
  onApprove
}: {
  run: RunRecord;
  approval: ApprovalDecision | null;
  diffSummary: RunDiffSummary | undefined;
  busy: boolean;
  navigate: (path: string) => void;
  onApprove: (run: RunRecord) => void;
}) {
  return (
    <article className="run-card">
      <button type="button" className="run-card-open" onClick={() => navigate(`/runs/${run.id}`)}>
        <span className="run-card-heading">
          <strong>{runWorkflowName(run)}</strong>
          <span className="mono">{shortRunId(run.id)}</span>
        </span>
        <span className="subtle">{runMetaLine(run)}</span>
        <span className="run-card-footer">
          <StatusBadge status={run.status} />
          <span title={formatDate(run.updated_at)}>{relativeTime(run.updated_at)}</span>
        </span>
        <DiffSummaryView summary={diffSummary} />
      </button>
      {approval ? (
        <span className="run-card-approval">
          <span>{approval.question}</span>
          <button type="button" disabled={busy} onClick={() => onApprove(run)}>
            Approve
          </button>
        </span>
      ) : null}
    </article>
  );
}

function EmptyRunState({ onLaunch }: { onLaunch: () => void }) {
  return (
    <EmptyState>
      <div className="empty-run-state">
        <strong>Launch your first run</strong>
        <span>No runs match this view.</span>
        <button type="button" onClick={onLaunch}>
          Launch your first run
        </button>
      </div>
    </EmptyState>
  );
}

interface DiffSummary {
  status: "ready";
  additions: number;
  deletions: number;
}

interface DiffUnavailable {
  status: "unavailable";
}

type RunDiffSummary = DiffSummary | DiffUnavailable;

function summarizeDiff(diff: RunDiff): DiffSummary {
  return diff.files.reduce(
    (summary, file) => ({
      status: "ready",
      additions: (summary.additions ?? 0) + file.additions,
      deletions: (summary.deletions ?? 0) + file.deletions
    }),
    { status: "ready", additions: 0, deletions: 0 } as DiffSummary
  );
}

function DiffSummaryView({ summary }: { summary: RunDiffSummary | undefined }) {
  if (!summary) {
    return <span className="diff-summary muted">Diff pending</span>;
  }
  if (summary.status === "unavailable") {
    return <span className="diff-summary muted">Diff unavailable</span>;
  }
  return (
    <span className="diff-summary" aria-label={`${summary.additions} additions, ${summary.deletions} deletions`}>
      <span className="diff-add">+{summary.additions}</span> <span className="diff-del">-{summary.deletions}</span>
    </span>
  );
}

function ValidationDiagnostics({ workflow }: { workflow: Workflow | null }) {
  const diagnostics = workflow?.diagnostics?.items ?? [];
  if (!workflow) {
    return <EmptyState>Select a workflow to see validation diagnostics</EmptyState>;
  }
  if (diagnostics.length === 0) {
    return <div className="notice">Workflow validation is clean.</div>;
  }
  return (
    <div className="diagnostics-list">
      {diagnostics.map((item, index) => (
        <div key={`${item.rule ?? "diagnostic"}-${index}`} className="diagnostic-row">
          <StatusBadge status={item.severity ?? "warn"} />
          <div>
            <strong>{item.rule ?? "Validation"}</strong>
            <div>{item.message}</div>
            {item.node_id ? <div className="subtle">Node: {item.node_id}</div> : null}
          </div>
        </div>
      ))}
    </div>
  );
}

function matchesStatus(run: RunRecord, filter: StatusFilter): boolean {
  if (filter === "all") {
    return true;
  }
  if (filter === "active") {
    return !isTerminalRunStatus(run.status);
  }
  if (filter === "running") {
    return run.status === "running" || run.status === "preparing";
  }
  if (filter === "completed") {
    return run.status === "completed" || run.status === "writeback_applied";
  }
  if (filter === "failed") {
    return run.status === "failed" || run.status === "writeback_failed";
  }
  return run.status === filter;
}

function matchesSearch(run: RunRecord, query: string): boolean {
  const normalized = query.trim().toLowerCase();
  if (!normalized) {
    return true;
  }
  return [
    run.id,
    runWorkflowName(run),
    run.actor_label,
    run.source_branch,
    run.source_commit,
    run.managed_branch,
    run.status
  ]
    .filter(Boolean)
    .some((value) => String(value).toLowerCase().includes(normalized));
}

function relativeTime(value: string | null | undefined): string {
  if (!value) {
    return "No timestamp";
  }
  const date = new Date(value);
  const delta = Date.now() - date.valueOf();
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

function canCancel(status: string): boolean {
  return !isTerminalRunStatus(status);
}
