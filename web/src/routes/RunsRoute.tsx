import { listRuns } from "../api";
import { LinkButton } from "../components/Layout";
import { useAsync } from "../components/useAsync";
import { EmptyState, ErrorBanner, Loading, PageHeader, Panel, StatusBadge, formatDate, shortSha } from "../components/ui";

export function RunsRoute({ navigate }: { navigate: (path: string) => void }) {
  const runsState = useAsync(listRuns, []);
  const runs = (runsState.data ?? []).slice().sort((a, b) => String(b.created_at ?? "").localeCompare(String(a.created_at ?? "")));

  return (
    <>
      <PageHeader title="Runs" />
      <ErrorBanner message={runsState.error} />
      <Panel title="Run List">
        {runsState.loading ? <Loading /> : null}
        {runs.length === 0 && !runsState.loading ? (
          <EmptyState>No runs</EmptyState>
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
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
    </>
  );
}
