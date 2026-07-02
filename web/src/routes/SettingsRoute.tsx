import { useMemo, useState } from "react";
import {
  deleteSettingsSecret,
  deleteSettingsVariable,
  getSettings,
  putSettingsSecret,
  putSettingsVariable,
  type SettingsOverview
} from "../api";
import { useAsync } from "../components/useAsync";
import {
  EmptyState,
  ErrorBanner,
  Field,
  KeyValue,
  Loading,
  PageHeader,
  Panel,
  StatusBadge,
  formatDate
} from "../components/ui";

type SettingsTab = "models" | "environments" | "variables" | "server" | "storage" | "monitoring";

const tabs: Array<{ id: SettingsTab; label: string }> = [
  { id: "models", label: "Models" },
  { id: "environments", label: "Environments" },
  { id: "variables", label: "Variables" },
  { id: "server", label: "Server" },
  { id: "storage", label: "Storage" },
  { id: "monitoring", label: "Monitoring" }
];

export function SettingsRoute() {
  const settingsState = useAsync(getSettings, []);
  const [activeTab, setActiveTab] = useState<SettingsTab>("models");
  const settings = settingsState.data;

  return (
    <>
      <PageHeader title="Settings" />
      <ErrorBanner message={settingsState.error} />
      {settingsState.loading ? <Loading /> : null}
      <nav className="tabs" aria-label="Settings sections">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            className={activeTab === tab.id ? "tab active" : "tab secondary"}
            type="button"
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </nav>
      {settings ? (
        <SettingsTabPanel
          activeTab={activeTab}
          settings={settings}
          refresh={settingsState.refresh}
        />
      ) : null}
    </>
  );
}

function SettingsTabPanel({
  activeTab,
  settings,
  refresh
}: {
  activeTab: SettingsTab;
  settings: SettingsOverview;
  refresh: () => void;
}) {
  if (activeTab === "models") {
    return <ModelsSettings settings={settings} refresh={refresh} />;
  }
  if (activeTab === "environments") {
    return <EnvironmentsSettings settings={settings} />;
  }
  if (activeTab === "variables") {
    return <VariablesSettings settings={settings} refresh={refresh} />;
  }
  if (activeTab === "server") {
    return <ServerSettings settings={settings} />;
  }
  if (activeTab === "storage") {
    return <StorageSettings settings={settings} />;
  }
  return <MonitoringSettings settings={settings} />;
}

function ModelsSettings({
  settings,
  refresh
}: {
  settings: SettingsOverview;
  refresh: () => void;
}) {
  const [draftSecrets, setDraftSecrets] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const credentials = useMemo(
    () => Object.values(settings.models.provider_credentials).sort((a, b) => a.name.localeCompare(b.name)),
    [settings.models.provider_credentials]
  );

  async function saveSecret(name: string) {
    const value = draftSecrets[name] ?? "";
    if (!value) {
      setError("Enter a secret value before saving");
      return;
    }
    setSaving(name);
    setError(null);
    try {
      await putSettingsSecret(name, value);
      setDraftSecrets((current) => ({ ...current, [name]: "" }));
      refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setSaving(null);
    }
  }

  async function clearSecret(name: string) {
    setSaving(name);
    setError(null);
    try {
      await deleteSettingsSecret(name);
      setDraftSecrets((current) => ({ ...current, [name]: "" }));
      refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setSaving(null);
    }
  }

  return (
    <>
      <Panel title="Defaults">
        <dl className="kv-grid">
          <KeyValue label="Default provider" value={settings.models.default_provider} />
          <KeyValue label="Default model" value={settings.models.default_model} />
        </dl>
      </Panel>
      <Panel title="Provider Credentials">
        <ErrorBanner message={error} />
        <table>
          <thead>
            <tr>
              <th>Provider</th>
              <th>Status</th>
              <th>Source</th>
              <th>Updated</th>
              <th>Secret</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {credentials.map((credential) => (
              <tr key={credential.name}>
                <td>{credential.name}</td>
                <td>
                  <StatusBadge status={credential.configured ? "configured" : "unconfigured"} />
                </td>
                <td>{credential.source}</td>
                <td>{formatDate(credential.updated_at)}</td>
                <td>
                  <input
                    aria-label={`${credential.name} secret`}
                    type="password"
                    value={draftSecrets[credential.name] ?? ""}
                    placeholder={credential.configured ? "Replace secret" : "Set secret"}
                    onChange={(event) =>
                      setDraftSecrets((current) => ({
                        ...current,
                        [credential.name]: event.target.value
                      }))
                    }
                  />
                </td>
                <td>
                  <div className="button-row">
                    <button
                      type="button"
                      disabled={saving === credential.name}
                      onClick={() => void saveSecret(credential.name)}
                    >
                      Save
                    </button>
                    <button
                      className="secondary"
                      type="button"
                      disabled={saving === credential.name || !credential.configured}
                      onClick={() => void clearSecret(credential.name)}
                    >
                      Clear
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </>
  );
}

function VariablesSettings({
  settings,
  refresh
}: {
  settings: SettingsOverview;
  refresh: () => void;
}) {
  const [key, setKey] = useState("");
  const [value, setValue] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function saveVariable() {
    if (!key) {
      setError("Enter a variable key before saving");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await putSettingsVariable(key, value);
      setKey("");
      setValue("");
      refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setSaving(false);
    }
  }

  async function removeVariable(variableKey: string) {
    setSaving(true);
    setError(null);
    try {
      await deleteSettingsVariable(variableKey);
      refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Panel title="Variables">
      <ErrorBanner message={error} />
      <div className="form-grid settings-variable-form">
        <Field label="Key">
          <input value={key} onChange={(event) => setKey(event.target.value)} />
        </Field>
        <Field label="Value">
          <input value={value} onChange={(event) => setValue(event.target.value)} />
        </Field>
        <button type="button" disabled={saving} onClick={() => void saveVariable()}>
          Save
        </button>
      </div>
      {settings.variables.items.length === 0 ? (
        <EmptyState>No variables configured</EmptyState>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Key</th>
              <th>Value</th>
              <th>Updated</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {settings.variables.items.map((variable) => (
              <tr key={variable.key}>
                <td className="mono">{variable.key}</td>
                <td>{variable.value}</td>
                <td>{formatDate(variable.updated_at)}</td>
                <td>
                  <button
                    className="secondary"
                    type="button"
                    disabled={saving}
                    onClick={() => void removeVariable(variable.key)}
                  >
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  );
}

function EnvironmentsSettings({ settings }: { settings: SettingsOverview }) {
  return (
    <Panel title="Environments">
      <dl className="kv-grid">
        <KeyValue label="Default" value={settings.environments.default} />
      </dl>
      <table>
        <thead>
          <tr>
            <th>Name</th>
            <th>Mode</th>
            <th>Description</th>
          </tr>
        </thead>
        <tbody>
          {settings.environments.items.map((environment) => (
            <tr key={environment.name}>
              <td>{environment.name}</td>
              <td>{environment.mode}</td>
              <td>{environment.description}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}

function ServerSettings({ settings }: { settings: SettingsOverview }) {
  return (
    <Panel title="Server">
      <dl className="kv-grid">
        <KeyValue label="Status" value={<StatusBadge status={settings.server.status} />} />
        <KeyValue label="Max concurrent runs" value={settings.server.max_concurrent_runs ?? "Unknown"} />
      </dl>
    </Panel>
  );
}

function StorageSettings({ settings }: { settings: SettingsOverview }) {
  return (
    <Panel title="Storage">
      <dl className="kv-grid">
        <KeyValue label="Status" value={<StatusBadge status={settings.storage.status} />} />
      </dl>
    </Panel>
  );
}

function MonitoringSettings({ settings }: { settings: SettingsOverview }) {
  return (
    <Panel title="Monitoring">
      <dl className="kv-grid">
        <KeyValue label="Active runs" value={settings.monitoring.active_runs} />
        <KeyValue label="Event stream" value={settings.monitoring.event_stream} />
      </dl>
    </Panel>
  );
}
