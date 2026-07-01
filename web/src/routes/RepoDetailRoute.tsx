import { getRepo, listWorkflows, type Workflow } from "../api";
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
  const repo = repoState.data;
  const workflows = workflowState.data ?? [];

  return (
    <>
      <PageHeader title={repo?.name ?? "Repo"} eyebrow={repoId} />
      <ErrorBanner message={repoState.error ?? workflowState.error} />
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
      <Panel title="Workflows">
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
