import { listRuns, type RunRecord } from "../api";
import { LinkButton } from "../components/Layout";
import { useAsync } from "../components/useAsync";
import { EmptyState, ErrorBanner, Loading, PageHeader, Panel, Stat, StatusBadge, formatDate } from "../components/ui";

const activeStatuses = new Set(["preparing", "running"]);
const failureStatuses = new Set(["failed", "writeback_failed", "cancelled"]);

export function DashboardRoute({ navigate }: { navigate: (path: string) => void }) {
  const runsState = useAsync(listRuns, []);
  const runs = runsState.data ?? [];
  const activeRuns = runs.filter((run) => activeStatuses.has(run.status));
  const queuedRuns = runs.filter((run) => run.status === "queued");
  const waitingRuns = runs.filter((run) => run.status === "waiting_for_approval");
  const recentFailures = runs
    .filter((run) => failureStatuses.has(run.status))
    .slice()
    .sort(sortNewest)
    .slice(0, 8);

  return (
    <>
      <PageHeader title="Operations Dashboard" eyebrow="Trusted LAN" />
      <ErrorBanner message={runsState.error} />
      {runsState.loading ? <Loading /> : null}
      <div className="stats-grid">
        <Stat label="Active runs" value={activeRuns.length} tone={activeRuns.length ? "warn" : "default"} />
        <Stat label="Queued runs" value={queuedRuns.length} tone={queuedRuns.length ? "warn" : "default"} />
        <Stat label="Waiting approvals" value={waitingRuns.length} tone={waitingRuns.length ? "warn" : "default"} />
        <Stat label="Recent failures" value={recentFailures.length} tone={recentFailures.length ? "bad" : "default"} />
      </div>
      <div className="dashboard-grid">
        <RunPanel title="Active Runs" runs={activeRuns} navigate={navigate} />
        <RunPanel title="Queued Runs" runs={queuedRuns} navigate={navigate} />
        <RunPanel title="Waiting Approvals" runs={waitingRuns} navigate={navigate} />
        <RunPanel title="Recent Failures" runs={recentFailures} navigate={navigate} />
      </div>
    </>
  );
}

function RunPanel({
  title,
  runs,
  navigate
}: {
  title: string;
  runs: RunRecord[];
  navigate: (path: string) => void;
}) {
  return (
    <Panel title={title}>
      {runs.length === 0 ? (
        <EmptyState>No runs</EmptyState>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Run</th>
              <th>Status</th>
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
                <td>{formatDate(run.updated_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  );
}

function sortNewest(a: RunRecord, b: RunRecord): number {
  return String(b.updated_at ?? "").localeCompare(String(a.updated_at ?? ""));
}
