import { useEffect, useState } from "react";
import { getRepo, listWorkflows, refreshRepo, type RepoRefreshResult, type Workflow } from "../api";
import { LinkButton } from "../components/Layout";
import { useAsync } from "../components/useAsync";
import { EmptyState, ErrorBanner, KeyValue, Loading, PageHeader, Panel, StatusBadge, formatDate, shortSha } from "../components/ui";

export function RepoDetailRoute({
  repoId,
  navigate
}: {
  repoId: string;
  navigate: (path: string) => void;
}) {
  const repoState = useAsync(() => getRepo(repoId), [repoId]);
  const workflowState = useAsync(() => listWorkflows(repoId), [repoId]);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshMessage, setRefreshMessage] = useState<string | null>(null);
  const [refreshError, setRefreshError] = useState<string | null>(null);
  const [activeWorkflowIds, setActiveWorkflowIds] = useState<string[] | null>(null);
  const repo = repoState.data;
  const workflows = filterActiveWorkflows(workflowState.data ?? [], activeWorkflowIds);

  useEffect(() => {
    let active = true;
    refreshRepo(repoId, { force: false })
      .then((result) => {
        if (!active) {
          return;
        }
        repoState.setData(result.repo);
        setActiveWorkflowIds(result.active_workflow_ids ?? null);
        workflowState.refresh();
      })
      .catch((caught: unknown) => {
        if (active) {
          setRefreshError(caught instanceof Error ? caught.message : String(caught));
        }
      });
    return () => {
      active = false;
    };
  }, [repoId]);

  async function runManualRefresh() {
    setRefreshing(true);
    setRefreshMessage(null);
    setRefreshError(null);
    try {
      const result = await refreshRepo(repoId, { force: true });
      repoState.setData(result.repo);
      setActiveWorkflowIds(result.active_workflow_ids ?? null);
      workflowState.refresh();
      setRefreshMessage(refreshResultMessage(result));
    } catch (caught) {
      setRefreshError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setRefreshing(false);
    }
  }

  return (
    <>
      <PageHeader title={repo?.name ?? "Repo"} eyebrow={repoId} />
      <ErrorBanner message={repoState.error ?? workflowState.error ?? refreshError} />
      {repoState.loading ? <Loading /> : null}
      {repo ? (
        <Panel title="Repo State">
          <dl className="kv-grid">
            <KeyValue label="Local path" value={<span className="path-cell">{repo.local_path}</span>} />
            <KeyValue label="Default branch" value={repo.default_branch} />
            <KeyValue label="Current commit" value={<span className="mono">{shortSha(repo.current_commit)}</span>} />
            <KeyValue label="Dirty state" value={repo.dirty_state} />
            <KeyValue label="Project config" value={<StatusBadge status={repo.project_config_status} />} />
            <KeyValue label="Updated" value={formatDate(repo.updated_at)} />
          </dl>
        </Panel>
      ) : null}
      <Panel
        title="Workflows"
        actions={
          <button type="button" className="secondary" disabled={refreshing} onClick={() => void runManualRefresh()}>
            {refreshing ? "Refreshing" : "Refresh"}
          </button>
        }
      >
        {refreshMessage ? <div className="notice repo-refresh-notice">{refreshMessage}</div> : null}
        {workflowState.loading ? <Loading /> : null}
        {workflows.length === 0 && !workflowState.loading ? (
          <EmptyState>No workflows discovered</EmptyState>
        ) : (
          <WorkflowTable workflows={workflows} navigate={navigate} />
        )}
      </Panel>
    </>
  );
}

function refreshResultMessage(result: RepoRefreshResult): string {
  const workflowLabel = result.workflow_count === 1 ? "workflow" : "workflows";
  const removed =
    result.removed_workflow_count > 0
      ? ` Removed ${result.removed_workflow_count} stale ${result.removed_workflow_count === 1 ? "workflow" : "workflows"}.`
      : "";
  const state = result.changed ? "Index refreshed." : "Index already current.";
  return `${state} ${result.workflow_count} ${workflowLabel} indexed.${removed}`;
}

function filterActiveWorkflows(workflows: Workflow[], activeWorkflowIds: string[] | null): Workflow[] {
  if (!activeWorkflowIds) {
    return workflows;
  }
  const active = new Set(activeWorkflowIds);
  return workflows.filter((workflow) => active.has(workflow.id));
}

function WorkflowTable({
  workflows,
  navigate
}: {
  workflows: Workflow[];
  navigate: (path: string) => void;
}) {
  return (
    <table>
      <thead>
        <tr>
          <th>Name</th>
          <th>Status</th>
          <th>DOT path</th>
          <th>Indexed</th>
        </tr>
      </thead>
      <tbody>
        {workflows.map((workflow) => (
          <tr key={workflow.id}>
            <td>
              <LinkButton to={`/workflows/${workflow.id}`} navigate={navigate}>
                {workflow.name}
              </LinkButton>
            </td>
            <td>
              <StatusBadge status={workflow.status} />
            </td>
            <td className="path-cell">{workflow.dot_path}</td>
            <td>{formatDate(workflow.indexed_at)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
