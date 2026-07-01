import { getSystemCapacity, getSystemHealth } from "../api";
import { useAsync } from "../components/useAsync";
import { ErrorBanner, KeyValue, Loading, PageHeader, Panel, Stat, StatusBadge } from "../components/ui";

export function SystemRoute() {
  const healthState = useAsync(getSystemHealth, []);
  const capacityState = useAsync(getSystemCapacity, []);
  const health = healthState.data;
  const capacity = capacityState.data;

  return (
    <>
      <PageHeader title="System" />
      <ErrorBanner message={healthState.error ?? capacityState.error} />
      {healthState.loading || capacityState.loading ? <Loading /> : null}
      <div className="stats-grid">
        <Stat label="Health" value={health ? <StatusBadge status={health.status} /> : "Unknown"} tone={health?.status === "ok" ? "good" : "default"} />
        <Stat label="Active runs" value={capacity?.active_runs ?? "Unknown"} tone={capacity?.active_runs ? "warn" : "default"} />
        <Stat label="Max concurrent" value={capacity?.max_concurrent_runs ?? "Unknown"} />
        <Stat label="Available slots" value={capacity?.available_slots ?? "Unknown"} />
      </div>
      <Panel title="Capacity">
        <dl className="kv-grid">
          <KeyValue label="Active runs" value={capacity?.active_runs ?? "Unknown"} />
          <KeyValue label="Max concurrent runs" value={capacity?.max_concurrent_runs ?? "Unknown"} />
          <KeyValue label="Available slots" value={capacity?.available_slots ?? "Unknown"} />
        </dl>
      </Panel>
    </>
  );
}
