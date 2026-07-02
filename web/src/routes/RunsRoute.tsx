import { useEffect, useMemo, useState, type FormEvent } from "react";
import {
  cancelRun,
  launchRun,
  listRepos,
  listRuns,
  listWorkflows,
  runSpecToLaunchInput,
  type RunRecord,
  type Workflow
} from "../api";
import { LinkButton } from "../components/Layout";
import { useAsync } from "../components/useAsync";
import { EmptyState, ErrorBanner, Field, Loading, PageHeader, Panel, StatusBadge, formatDate, shortSha } from "../components/ui";

export function RunsRoute({ navigate }: { navigate: (path: string) => void }) {
  const [statusFilter, setStatusFilter] = useState("");
  const [repoFilter, setRepoFilter] = useState("");
  const runsState = useAsync(
    () => listRuns({ status: statusFilter, repo_id: repoFilter }),
    [statusFilter, repoFilter]
  );
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
  const runs = (runsState.data ?? []).slice().sort((a, b) => String(b.created_at ?? "").localeCompare(String(a.created_at ?? "")));
  const selectedWorkflow = useMemo(
    () => workflows.find((workflow) => workflow.name === workflowName) ?? workflows[0] ?? null,
    [workflowName, workflows]
  );

  useEffect(() => {
    const timer = window.setInterval(() => runsState.refresh(), 4000);
    return () => window.clearInterval(timer);
  }, [runsState.refresh]);

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

  return (
    <>
      <PageHeader title="Runs" />
      <ErrorBanner message={runsState.error ?? reposState.error ?? workflowsState.error ?? actionError} />
      {actionMessage ? <div className="notice">{actionMessage}</div> : null}
      <Panel title="Launch Run">
        {reposState.loading ? <Loading label="Loading repos" /> : null}
        <form className="launch-form" onSubmit={submitLaunch}>
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
          <button type="submit" disabled={launching || !selectedRepo || !selectedWorkflow}>
            {launching ? "Launching" : "Launch"}
          </button>
        </form>
        <ValidationDiagnostics workflow={selectedWorkflow} />
      </Panel>
      <Panel
        title="Run List"
        actions={
          <div className="filter-row">
            <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
              <option value="">All statuses</option>
              <option value="queued">Queued</option>
              <option value="preparing">Preparing</option>
              <option value="running">Running</option>
              <option value="waiting_for_approval">Waiting approval</option>
              <option value="completed">Completed</option>
              <option value="failed">Failed</option>
              <option value="cancelled">Cancelled</option>
            </select>
            <select value={repoFilter} onChange={(event) => setRepoFilter(event.target.value)}>
              <option value="">All repos</option>
              {(reposState.data ?? []).map((repo) => (
                <option key={repo.id} value={repo.id}>
                  {repo.name}
                </option>
              ))}
            </select>
            <button type="button" className="secondary" onClick={() => runsState.refresh()}>
              Refresh
            </button>
          </div>
        }
      >
        {runsState.loading ? <Loading /> : null}
        {runs.length === 0 && !runsState.loading ? (
          <EmptyState>No runs match the current filters</EmptyState>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Run</th>
                <th>Status</th>
                <th>Workflow</th>
                <th>Source</th>
                <th>Managed branch</th>
                <th>Updated</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.id}>
                  <td>
                    <LinkButton to={`/runs/${run.id}`} navigate={navigate}>
                      {run.id}
                    </LinkButton>
                  </td>
                  <td>
                    <StatusBadge status={run.status} />
                  </td>
                  <td className="mono">{run.workflow_id}</td>
                  <td className="mono">{shortSha(run.source_commit)}</td>
                  <td className="path-cell">{run.managed_branch ?? "None"}</td>
                  <td>{formatDate(run.updated_at)}</td>
                  <td>
                    <div className="button-row">
                      <button type="button" className="secondary" disabled={!canCancel(run.status) || busyRunId === run.id} onClick={() => cancel(run)}>
                        Cancel
                      </button>
                      <button type="button" disabled={busyRunId === run.id} onClick={() => rerun(run)}>
                        Re-run
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
    </>
  );
}

function canCancel(status: string): boolean {
  return !["completed", "failed", "cancelled", "writeback_applied", "writeback_failed"].includes(status);
}

function ValidationDiagnostics({ workflow }: { workflow: Workflow | null }) {
  const diagnostics = workflow?.diagnostics?.items ?? [];
  if (!workflow) {
    return <EmptyState>Select a workflow to see validation diagnostics</EmptyState>;
  }
  if (workflow.diagnostics?.error) {
    return <ErrorBanner message={workflow.diagnostics.error} />;
  }
  if (diagnostics.length === 0) {
    return <div className="notice">No validation diagnostics for {workflow.name}</div>;
  }
  return (
    <div className="diagnostics-list">
      {diagnostics.map((diagnostic, index) => (
        <div key={`${diagnostic.rule ?? "diagnostic"}-${index}`} className="diagnostic-row">
          <StatusBadge status={diagnostic.severity ?? "info"} />
          <span>{diagnostic.message}</span>
        </div>
      ))}
    </div>
  );
}
