import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import {
  answerApproval,
  artifactUrl,
  cancelRun,
  getRun,
  getRunDiff,
  knownRunEventTypes,
  launchRun,
  listApprovals,
  listArtifacts,
  listCheckpoints,
  listRunEvents,
  openRunEventSource,
  promoteWriteBack,
  runSpecToLaunchInput,
  type ApprovalDecision,
  type ArtifactRecord,
  type CheckpointRecord,
  type RunDiff,
  type RunEvent
} from "../api";
import { GraphViewer } from "../components/GraphViewer";
import { useAsync } from "../components/useAsync";
import {
  canCancelRunStatus,
  eventFromSseMessage,
  isWorkspaceCleanedDiffError,
  mergeRunEvents,
  runWorkflowName
} from "../runViewModel";
import {
  CopyButton,
  CopyableTruncatedValue,
  DiffViewer,
  EmptyState,
  ErrorBanner,
  Field,
  KeyValue,
  Loading,
  PageHeader,
  Panel,
  RelativeTime,
  StatusBadge,
  formatDate,
  formatDuration,
  formatRelativeTime,
  shortSha
} from "../components/ui";

interface RunRelated {
  events: RunEvent[];
  approvals: ApprovalDecision[];
  artifacts: ArtifactRecord[];
  checkpoints: CheckpointRecord[];
}

export function RunDetailRoute({ runId }: { runId: string }) {
  const runState = useAsync(() => getRun(runId), [runId]);
  const relatedState = useAsync<RunRelated>(
    async () => {
      const [events, approvals, artifacts, checkpoints] = await Promise.all([
        listRunEvents(runId),
        listApprovals(runId),
        listArtifacts(runId),
        listCheckpoints(runId)
      ]);
      return { events, approvals, artifacts, checkpoints };
    },
    [runId]
  );
  const diffState = useAsync(() => getRunDiff(runId, { includePatch: true }), [runId]);
  const [liveEvents, setLiveEvents] = useState<RunEvent[]>([]);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [actionBusy, setActionBusy] = useState(false);
  const refreshTimer = useRef<number | null>(null);
  const run = runState.data;
  const related = relatedState.data;
  const events = useMemo(
    () => mergeEvents([...(related?.events ?? []), ...liveEvents]),
    [related?.events, liveEvents]
  );
  const scheduleRefresh = useCallback(() => {
    if (refreshTimer.current !== null) {
      return;
    }
    refreshTimer.current = window.setTimeout(() => {
      refreshTimer.current = null;
      runState.refresh();
      relatedState.refresh();
    }, 500);
  }, [runState.refresh, relatedState.refresh]);

  useEffect(() => {
    setLiveEvents([]);
    const source = openRunEventSource(runId);
    const handlers: Array<[string, EventListener]> = [];

    for (const eventType of knownRunEventTypes) {
      const handler = ((message: MessageEvent<string>) => {
        const event = eventFromSse(eventType, message);
        if (event) {
          setLiveEvents((current) => mergeEvents([...current, event]));
          scheduleRefresh();
        }
      }) as EventListener;
      source.addEventListener(eventType, handler);
      handlers.push([eventType, handler]);
    }

    source.onerror = () => {
      if (run?.status && isTerminal(run.status)) {
        source.close();
      }
    };

    return () => {
      for (const [eventType, handler] of handlers) {
        source.removeEventListener(eventType, handler);
      }
      source.close();
    };
  }, [runId, run?.status, scheduleRefresh]);

  useEffect(() => {
    return () => {
      if (refreshTimer.current !== null) {
        window.clearTimeout(refreshTimer.current);
      }
    };
  }, []);

  return (
    <>
      <a className="back-link" href="../runs">
        ← Back to runs
      </a>
      <PageHeader
        title={run ? runWorkflowName(run) : "Run detail"}
        eyebrow="Run Detail"
        subline={run ? <RunHeaderSubline run={run} /> : null}
        actions={
          run ? (
            <RunActions
              run={run}
              busy={actionBusy}
              onBusy={setActionBusy}
              onMessage={setActionMessage}
              onError={setActionError}
              onChanged={() => {
                runState.refresh();
                relatedState.refresh();
                diffState.refresh();
              }}
            />
          ) : null
        }
      />
      <ErrorBanner message={runState.error ?? relatedState.error ?? actionError} />
      {actionMessage ? <div className="notice">{actionMessage}</div> : null}
      {runState.loading ? <Loading /> : null}
      {run ? (
        <>
          <Panel title="Run Status">
            <dl className="kv-grid">
              <KeyValue label="Durable status" value={<StatusBadge status={run.status} />} />
              <KeyValue label="Source branch" value={run.source_branch ? <CopyableTruncatedValue value={run.source_branch} /> : "Not exposed"} />
              <KeyValue label="Source commit" value={run.source_commit ? <CopyableTruncatedValue value={run.source_commit} /> : "Not exposed"} />
              <KeyValue label="Managed branch" value={run.managed_branch ? <CopyableTruncatedValue value={run.managed_branch} /> : "None"} />
              <KeyValue label="Worktree" value={run.worktree_path ? <CopyableTruncatedValue value={run.worktree_path} /> : "None"} />
              <KeyValue label="Actor" value={run.actor_label || "None"} />
              <KeyValue label="Started" value={formatDate(run.started_at)} />
              <KeyValue label="Completed" value={formatDate(run.completed_at)} />
            </dl>
            {run.error_message ? <div className="error-banner">{run.error_message}</div> : null}
          </Panel>
          <Panel title="Branch Diff">
            <BranchDiffPanel diff={diffState.data} loading={diffState.loading} error={diffState.error} />
          </Panel>
          <GraphViewer workflowId={run.workflow_id} events={events} />
          <PendingApprovals
            runId={runId}
            runStatus={run.status}
            approvals={related?.approvals ?? []}
            onChanged={() => {
              runState.refresh();
              relatedState.refresh();
            }}
          />
          <Panel title="Event Timeline">
            <EventTimeline events={events} loading={relatedState.loading} />
          </Panel>
          <Panel title="Artifacts">
            <ArtifactTable runId={runId} artifacts={related?.artifacts ?? []} loading={relatedState.loading} />
          </Panel>
          <Panel title="Checkpoints">
            <CheckpointTable checkpoints={related?.checkpoints ?? []} loading={relatedState.loading} />
          </Panel>
        </>
      ) : null}
    </>
  );
}

function RunHeaderSubline({
  run
}: {
  run: {
    id: string;
    source_branch?: string;
    status: string;
    managed_branch: string | null;
    created_at: string | null;
    started_at: string | null;
    completed_at: string | null;
  };
}) {
  return (
    <div className="run-header-subline">
      <StatusBadge status={run.status} />
      <span className="copyable-value">
        <span className="mono">{shortSha(run.id)}</span>
        <CopyButton value={run.id} label="Copy run id" />
      </span>
      <span>
        {run.source_branch || "source"} -&gt; {run.managed_branch || "managed branch pending"}
      </span>
      <RelativeTime value={run.created_at} />
      <span>{formatDuration(run.started_at ?? run.created_at, run.completed_at)}</span>
    </div>
  );
}

function RunActions({
  run,
  busy,
  onBusy,
  onMessage,
  onError,
  onChanged
}: {
  run: {
    id: string;
    status: string;
    managed_branch: string | null;
    run_spec: Parameters<typeof runSpecToLaunchInput>[0];
  };
  busy: boolean;
  onBusy: (value: boolean) => void;
  onMessage: (value: string | null) => void;
  onError: (value: string | null) => void;
  onChanged: () => void;
}) {
  const [targetBranch, setTargetBranch] = useState(`attractor/accepted/${run.id}`);
  const [actorLabel, setActorLabel] = useState("operator");
  const [overwrite, setOverwrite] = useState(false);
  const [allowProtected, setAllowProtected] = useState(false);
  const canPromote = run.status === "completed" && Boolean(run.managed_branch);

  async function cancelCurrentRun() {
    onBusy(true);
    onMessage(null);
    onError(null);
    try {
      const result = await cancelRun(run.id);
      onMessage(`${run.id}: ${result.status}`);
      onChanged();
    } catch (caught) {
      onError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      onBusy(false);
    }
  }

  async function rerunCurrentRun() {
    const input = runSpecToLaunchInput(run.run_spec);
    if (!input) {
      onError("This run does not include enough run_spec metadata to re-run.");
      return;
    }
    onBusy(true);
    onMessage(null);
    onError(null);
    try {
      const nextRun = await launchRun(input);
      onMessage(`Re-ran ${run.id} as ${nextRun.id}`);
      onChanged();
    } catch (caught) {
      onError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      onBusy(false);
    }
  }

  async function promoteCurrentRun(event: FormEvent) {
    event.preventDefault();
    onBusy(true);
    onMessage(null);
    onError(null);
    try {
      const result = await promoteWriteBack(run.id, {
        target_branch: targetBranch,
        actor_label: actorLabel,
        overwrite,
        allow_protected: allowProtected
      });
      onMessage(`${result.status}: ${result.commit_sha ?? result.error_message ?? result.target_branch}`);
      onChanged();
    } catch (caught) {
      onError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      onBusy(false);
    }
  }

  return (
    <div className="run-action-cluster">
      {canPromote ? (
        <details className="action-popover">
          <summary className="button-like primary">Promote branch</summary>
          <form className="action-popover-form" onSubmit={promoteCurrentRun}>
            <Field label="Target branch">
              <input value={targetBranch} onChange={(event) => setTargetBranch(event.target.value)} required />
            </Field>
            <Field label="Actor">
              <input value={actorLabel} onChange={(event) => setActorLabel(event.target.value)} required />
            </Field>
            <label className="check-field">
              <input type="checkbox" checked={overwrite} onChange={(event) => setOverwrite(event.target.checked)} />
              <span>Overwrite</span>
            </label>
            <label className="check-field">
              <input type="checkbox" checked={allowProtected} onChange={(event) => setAllowProtected(event.target.checked)} />
              <span>Allow protected</span>
            </label>
            <button type="submit" disabled={busy}>
              Promote
            </button>
          </form>
        </details>
      ) : null}
      <button type="button" className="secondary" disabled={busy || !runSpecToLaunchInput(run.run_spec)} onClick={rerunCurrentRun}>
        Re-run
      </button>
      {canCancel(run.status) ? (
        <button type="button" className="secondary" disabled={busy} onClick={cancelCurrentRun}>
          Cancel
        </button>
      ) : null}
    </div>
  );
}

function BranchDiff({ diff, loading }: { diff: RunDiff | null; loading: boolean }) {
  if (loading) {
    return <Loading label="Loading diff" />;
  }
  if (!diff) {
    return <EmptyState>No diff loaded</EmptyState>;
  }
  if (diff.files.length === 0) {
    return <EmptyState>No file changes between source and run HEAD</EmptyState>;
  }
  return (
    <>
      <dl className="kv-grid">
        <KeyValue label="Base" value={<span className="mono">{shortSha(diff.base_commit)}</span>} />
        <KeyValue label="Head" value={<span className="mono">{shortSha(diff.head_commit)}</span>} />
        <KeyValue label="Files" value={diff.files.length} />
        <KeyValue label="Truncated" value={diff.truncated ? "Yes" : "No"} />
      </dl>
      <div className="diff-file-list">
        {diff.files.map((file) => (
          <details className="diff-file-row" key={file.path}>
            <summary>
              <span className="path-cell">{file.path}</span>
              <span className="status status-neutral">{file.status}</span>
              <span className="diff-counts">
                <span className="diff-add">+{file.additions}</span>
                <span className="diff-del">-{file.deletions}</span>
              </span>
            </summary>
            <DiffViewer patch={file.patch} truncated={file.patch_truncated} />
          </details>
        ))}
      </div>
    </>
  );
}

function BranchDiffPanel({
  diff,
  loading,
  error
}: {
  diff: RunDiff | null;
  loading: boolean;
  error: string | null;
}) {
  if (isWorkspaceCleanedDiffError(error)) {
    return <EmptyState>diff unavailable — workspace was cleaned up</EmptyState>;
  }
  return (
    <>
      <ErrorBanner message={error} />
      <BranchDiff diff={diff} loading={loading} />
    </>
  );
}

function PendingApprovals({
  runId,
  runStatus,
  approvals,
  onChanged
}: {
  runId: string;
  runStatus: string;
  approvals: ApprovalDecision[];
  onChanged: () => void;
}) {
  const pending = approvals.filter((approval) => approval.status === "pending");
  if (runStatus !== "waiting_for_approval" || pending.length === 0) {
    return null;
  }
  return (
    <Panel title="Pending Approvals">
      <div className="approval-list">
        {pending.map((approval) => (
          <ApprovalControl key={approval.id} runId={runId} approval={approval} onChanged={onChanged} />
        ))}
      </div>
    </Panel>
  );
}

function ApprovalControl({
  runId,
  approval,
  onChanged
}: {
  runId: string;
  approval: ApprovalDecision;
  onChanged: () => void;
}) {
  const [actorLabel, setActorLabel] = useState("operator");
  const [answer, setAnswer] = useState("approve");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(nextAnswer: string) {
    setBusy(true);
    setError(null);
    try {
      await answerApproval(runId, approval.id, { answer: nextAnswer, actor_label: actorLabel });
      onChanged();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="approval-row">
      <div>
        <strong>{approval.question}</strong>
        <div className="subtle">{approval.node_id ?? approval.id}</div>
        <ErrorBanner message={error} />
      </div>
      <Field label="Actor">
        <input value={actorLabel} onChange={(event) => setActorLabel(event.target.value)} />
      </Field>
      <Field label="Answer">
        <input value={answer} onChange={(event) => setAnswer(event.target.value)} />
      </Field>
      <div className="button-row">
        <button type="button" disabled={busy} onClick={() => submit(answer)}>
          Submit
        </button>
        <button type="button" disabled={busy} className="secondary" onClick={() => submit("reject")}>
          Reject
        </button>
      </div>
    </div>
  );
}

function EventTimeline({ events, loading }: { events: RunEvent[]; loading: boolean }) {
  if (loading) {
    return <Loading />;
  }
  if (events.length === 0) {
    return <EmptyState>No events</EmptyState>;
  }
  return (
    <ol className="event-timeline">
      {events.map((event) => (
        <li className="event-row" key={`${event.sequence}-${event.event_type}`}>
          <span className={`event-icon event-icon-${eventTone(event.event_type)}`} aria-hidden="true">
            {eventIcon(event.event_type)}
          </span>
          <div className="event-body">
            <div className="event-title-row">
              <strong>{eventLabel(event.event_type)}</strong>
              <span className="subtle">{formatRelativeTime(event.created_at)}</span>
            </div>
            <div>{eventSummary(event)}</div>
            <div className="event-meta">
              <span className="mono">#{event.sequence}</span>
              {event.actor_label ? <span>{event.actor_label}</span> : null}
              <span>{formatDate(event.created_at)}</span>
            </div>
            <details className="raw-expander">
              <summary>View raw</summary>
              <pre className="payload">{JSON.stringify(event.payload, null, 2)}</pre>
            </details>
          </div>
        </li>
      ))}
    </ol>
  );
}

function eventLabel(type: string): string {
  return type
    .split(".")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function eventIcon(type: string): string {
  if (type.includes("failed")) {
    return "!";
  }
  if (type.includes("approval")) {
    return "?";
  }
  if (type.includes("checkpoint")) {
    return "C";
  }
  if (type.includes("completed") || type.includes("applied")) {
    return "OK";
  }
  return "i";
}

function eventTone(type: string): "running" | "waiting" | "completed" | "failed" | "neutral" {
  if (type.includes("failed") || type.includes("cancelled")) {
    return "failed";
  }
  if (type.includes("approval") || type.includes("retrying")) {
    return "waiting";
  }
  if (type.includes("completed") || type.includes("saved") || type.includes("applied")) {
    return "completed";
  }
  if (type.includes("started") || type.includes("queued") || type.includes("preparing")) {
    return "running";
  }
  return "neutral";
}

function eventSummary(event: RunEvent): string {
  const node = stringPayload(event.payload, "node_id") ?? stringPayload(event.payload, "name");
  const commit = shortSha(stringPayload(event.payload, "commit_sha"));
  const output = stringPayload(event.payload, "output") ?? stringPayload(event.payload, "message");
  switch (event.event_type) {
    case "run.queued":
      return `Queued ${stringPayload(event.payload, "workflow_name") ?? "workflow run"}`;
    case "run.started":
      return "Run started";
    case "run.completed":
      return "Run completed";
    case "run.failed":
      return output || "Run failed";
    case "stage.started":
      return node ? `${node} started` : "Stage started";
    case "stage.completed":
      return node ? `${node} completed` : "Stage completed";
    case "stage.failed":
      return node ? `${node} failed` : "Stage failed";
    case "approval.requested":
      return node ? `Approval requested at ${node}` : "Approval requested";
    case "approval.decided":
      return `Approval ${stringPayload(event.payload, "answer") ?? "decided"}`;
    case "checkpoint.saved":
      return node ? `Checkpoint saved for ${node} at ${commit}` : `Checkpoint saved ${commit}`;
    case "writeback.applied":
      return `Write-back applied to ${stringPayload(event.payload, "target_branch") ?? "target branch"}`;
    case "pipeline.event":
      return output || "Agent output received";
    default:
      return output || eventLabel(event.event_type);
  }
}

function stringPayload(payload: Record<string, unknown>, key: string): string | null {
  const value = payload[key];
  return typeof value === "string" && value.length > 0 ? value : null;
}

function ArtifactTable({
  runId,
  artifacts,
  loading
}: {
  runId: string;
  artifacts: ArtifactRecord[];
  loading: boolean;
}) {
  if (loading) {
    return <Loading />;
  }
  if (artifacts.length === 0) {
    return <EmptyState>No artifacts</EmptyState>;
  }
  return (
    <table>
      <thead>
        <tr>
          <th>Name</th>
          <th>Kind</th>
          <th>Media</th>
          <th>Size</th>
          <th>URI</th>
        </tr>
      </thead>
      <tbody>
        {artifacts.map((artifact) => (
          <tr key={artifact.id ?? artifact.uri}>
            <td>
              {artifact.id ? (
                <a href={artifactUrl(runId, artifact.id)}>{artifact.name}</a>
              ) : (
                artifact.name
              )}
            </td>
            <td>{artifact.kind}</td>
            <td>{artifact.media_type}</td>
            <td>{artifact.size_bytes}</td>
            <td>{artifact.uri ? <CopyableTruncatedValue value={artifact.uri} /> : "None"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function CheckpointTable({ checkpoints, loading }: { checkpoints: CheckpointRecord[]; loading: boolean }) {
  if (loading) {
    return <Loading />;
  }
  if (checkpoints.length === 0) {
    return <EmptyState>No checkpoints</EmptyState>;
  }
  return (
    <table>
      <thead>
        <tr>
          <th>Stage</th>
          <th>Node</th>
          <th>Commit</th>
          <th>Ref</th>
          <th>Created</th>
        </tr>
      </thead>
      <tbody>
        {checkpoints.map((checkpoint) => (
          <tr key={checkpoint.id ?? `${checkpoint.stage_index}-${checkpoint.commit_sha}`}>
            <td>{checkpoint.stage_index}</td>
            <td>{checkpoint.node_id}</td>
            <td className="mono">{shortSha(checkpoint.commit_sha)}</td>
            <td>{checkpoint.ref_name ? <CopyableTruncatedValue value={checkpoint.ref_name} /> : "None"}</td>
            <td>{formatDate(checkpoint.created_at)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function eventFromSse(eventType: string, message: MessageEvent<string>): RunEvent | null {
  return eventFromSseMessage(eventType, message);
}

function mergeEvents(events: RunEvent[]): RunEvent[] {
  return mergeRunEvents(events);
}

function isTerminal(status: string): boolean {
  return ["completed", "failed", "cancelled", "writeback_applied", "writeback_failed"].includes(status);
}

function canCancel(status: string): boolean {
  return canCancelRunStatus(status);
}
