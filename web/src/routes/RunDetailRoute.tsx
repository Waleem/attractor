import { useEffect, useMemo, useState, type FormEvent } from "react";
import {
  answerApproval,
  getRun,
  knownRunEventTypes,
  listApprovals,
  listArtifacts,
  listCheckpoints,
  listRunEvents,
  openRunEventSource,
  promoteWriteBack,
  type ApprovalDecision,
  type ArtifactRecord,
  type CheckpointRecord,
  type RunEvent
} from "../api";
import { useAsync } from "../components/useAsync";
import { EmptyState, ErrorBanner, Field, KeyValue, Loading, PageHeader, Panel, StatusBadge, formatDate, shortSha } from "../components/ui";

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
  const [liveEvents, setLiveEvents] = useState<RunEvent[]>([]);
  const run = runState.data;
  const related = relatedState.data;
  const events = useMemo(
    () => mergeEvents([...(related?.events ?? []), ...liveEvents]),
    [related?.events, liveEvents]
  );

  useEffect(() => {
    setLiveEvents([]);
    const source = openRunEventSource(runId);
    const handlers: Array<[string, EventListener]> = [];

    for (const eventType of knownRunEventTypes) {
      const handler = ((message: MessageEvent<string>) => {
        const event = eventFromSse(eventType, message);
        if (event) {
          setLiveEvents((current) => mergeEvents([...current, event]));
          runState.refresh();
          relatedState.refresh();
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
  }, [runId, run?.status, runState.refresh, relatedState.refresh]);

  return (
    <>
      <PageHeader title={run?.id ?? "Run"} eyebrow="Run Detail" />
      <ErrorBanner message={runState.error ?? relatedState.error} />
      {runState.loading ? <Loading /> : null}
      {run ? (
        <>
          <Panel title="Run Status">
            <dl className="kv-grid">
              <KeyValue label="Durable status" value={<StatusBadge status={run.status} />} />
              <KeyValue label="Source branch" value={run.source_branch ?? "Not exposed"} />
              <KeyValue label="Source commit" value={<span className="mono">{shortSha(run.source_commit) || "Not exposed"}</span>} />
              <KeyValue label="Managed branch" value={<span className="path-cell">{run.managed_branch ?? "None"}</span>} />
              <KeyValue label="Worktree" value={<span className="path-cell">{run.worktree_path ?? "None"}</span>} />
              <KeyValue label="Actor" value={run.actor_label || "None"} />
              <KeyValue label="Started" value={formatDate(run.started_at)} />
              <KeyValue label="Completed" value={formatDate(run.completed_at)} />
            </dl>
            {run.error_message ? <div className="error-banner">{run.error_message}</div> : null}
          </Panel>
          <PendingApprovals
            runId={runId}
            runStatus={run.status}
            approvals={related?.approvals ?? []}
            onChanged={() => {
              runState.refresh();
              relatedState.refresh();
            }}
          />
          <WriteBackAction
            runId={runId}
            status={run.status}
            managedBranch={run.managed_branch}
            onChanged={() => {
              runState.refresh();
              relatedState.refresh();
            }}
          />
          <Panel title="Event Timeline">
            <EventTable events={events} loading={relatedState.loading} />
          </Panel>
          <Panel title="Artifacts">
            <ArtifactTable artifacts={related?.artifacts ?? []} loading={relatedState.loading} />
          </Panel>
          <Panel title="Checkpoints">
            <CheckpointTable checkpoints={related?.checkpoints ?? []} loading={relatedState.loading} />
          </Panel>
        </>
      ) : null}
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

function WriteBackAction({
  runId,
  status,
  managedBranch,
  onChanged
}: {
  runId: string;
  status: string;
  managedBranch: string | null;
  onChanged: () => void;
}) {
  const [targetBranch, setTargetBranch] = useState(`attractor/accepted/${runId}`);
  const [actorLabel, setActorLabel] = useState("operator");
  const [overwrite, setOverwrite] = useState(false);
  const [allowProtected, setAllowProtected] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const canWriteBack = status === "completed" && Boolean(managedBranch);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      const result = await promoteWriteBack(runId, {
        target_branch: targetBranch,
        actor_label: actorLabel,
        overwrite,
        allow_protected: allowProtected
      });
      setMessage(`${result.status}: ${result.commit_sha ?? result.error_message ?? result.target_branch}`);
      onChanged();
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }

  if (!canWriteBack) {
    return null;
  }
  return (
    <Panel title="Write-Back">
      <form className="form-grid writeback-form" onSubmit={submit}>
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
      {message ? <div className="notice">{message}</div> : null}
    </Panel>
  );
}

function EventTable({ events, loading }: { events: RunEvent[]; loading: boolean }) {
  if (loading) {
    return <Loading />;
  }
  if (events.length === 0) {
    return <EmptyState>No events</EmptyState>;
  }
  return (
    <table>
      <thead>
        <tr>
          <th>Seq</th>
          <th>Event</th>
          <th>Actor</th>
          <th>Created</th>
          <th>Payload</th>
        </tr>
      </thead>
      <tbody>
        {events.map((event) => (
          <tr key={`${event.sequence}-${event.event_type}`}>
            <td className="mono">{event.sequence}</td>
            <td>{event.event_type}</td>
            <td>{event.actor_label || "None"}</td>
            <td>{formatDate(event.created_at)}</td>
            <td>
              <code className="payload">{JSON.stringify(event.payload)}</code>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ArtifactTable({ artifacts, loading }: { artifacts: ArtifactRecord[]; loading: boolean }) {
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
            <td>{artifact.name}</td>
            <td>{artifact.kind}</td>
            <td>{artifact.media_type}</td>
            <td>{artifact.size_bytes}</td>
            <td className="path-cell">{artifact.uri}</td>
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
            <td className="path-cell">{checkpoint.ref_name}</td>
            <td>{formatDate(checkpoint.created_at)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function eventFromSse(eventType: string, message: MessageEvent<string>): RunEvent | null {
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
    actor_label: "",
    created_at: new Date().toISOString()
  };
}

function mergeEvents(events: RunEvent[]): RunEvent[] {
  const bySequence = new Map<number, RunEvent>();
  for (const event of events) {
    bySequence.set(event.sequence, event);
  }
  return Array.from(bySequence.values()).sort((a, b) => a.sequence - b.sequence);
}

function isTerminal(status: string): boolean {
  return ["completed", "failed", "cancelled", "writeback_applied", "writeback_failed"].includes(status);
}
