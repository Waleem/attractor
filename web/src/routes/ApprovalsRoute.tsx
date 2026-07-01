import { useMemo } from "react";
import { listApprovals, listRuns, type ApprovalDecision, type RunRecord } from "../api";
import { LinkButton } from "../components/Layout";
import { useAsync } from "../components/useAsync";
import { EmptyState, ErrorBanner, Loading, PageHeader, Panel, StatusBadge, formatDate } from "../components/ui";

interface PendingApprovalItem {
  run: RunRecord;
  approval: ApprovalDecision;
}

interface ApprovalSummary {
  pending: PendingApprovalItem[];
  writeBackReady: RunRecord[];
}

export function ApprovalsRoute({ navigate }: { navigate: (path: string) => void }) {
  const summaryState = useAsync<ApprovalSummary>(async () => {
    const runs = await listRuns();
    const waitingRuns = runs.filter((run) => run.status === "waiting_for_approval");
    const approvals = await Promise.all(
      waitingRuns.map(async (run) => ({
        run,
        approvals: await listApprovals(run.id)
      }))
    );
    return {
      pending: approvals.flatMap(({ run, approvals: runApprovals }) =>
        runApprovals
          .filter((approval) => approval.status === "pending")
          .map((approval) => ({ run, approval }))
      ),
      writeBackReady: runs.filter((run) => run.status === "completed" && Boolean(run.managed_branch))
    };
  }, []);

  const pending = summaryState.data?.pending ?? [];
  const writeBackReady = summaryState.data?.writeBackReady ?? [];
  const total = useMemo(() => pending.length + writeBackReady.length, [pending.length, writeBackReady.length]);

  return (
    <>
      <PageHeader title="Approvals" eyebrow={`${total} open`} />
      <ErrorBanner message={summaryState.error} />
      {summaryState.loading ? <Loading /> : null}
      <Panel title="Pending Human Gates">
        {pending.length === 0 && !summaryState.loading ? (
          <EmptyState>No pending gates</EmptyState>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Run</th>
                <th>Question</th>
                <th>Node</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {pending.map(({ run, approval }) => (
                <tr key={approval.id}>
                  <td>
                    <LinkButton to={`/runs/${run.id}`} navigate={navigate}>
                      {run.id}
                    </LinkButton>
                  </td>
                  <td>{approval.question}</td>
                  <td>{approval.node_id ?? "None"}</td>
                  <td>{formatDate(approval.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
      <Panel title="Write-Back Approvals">
        {writeBackReady.length === 0 && !summaryState.loading ? (
          <EmptyState>No completed runs awaiting write-back</EmptyState>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Run</th>
                <th>Status</th>
                <th>Managed branch</th>
                <th>Completed</th>
              </tr>
            </thead>
            <tbody>
              {writeBackReady.map((run) => (
                <tr key={run.id}>
                  <td>
                    <LinkButton to={`/runs/${run.id}`} navigate={navigate}>
                      {run.id}
                    </LinkButton>
                  </td>
                  <td>
                    <StatusBadge status={run.status} />
                  </td>
                  <td className="path-cell">{run.managed_branch}</td>
                  <td>{formatDate(run.completed_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
    </>
  );
}
