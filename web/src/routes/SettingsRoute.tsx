import { useMemo, useState } from "react";
import {
  deleteSettingsSecret,
  deleteSettingsVariable,
  getModelCatalog,
  getSettings,
  putSettingsSecret,
  putSettingsVariable,
  testModels,
  type ModelCatalogRow,
  type ModelTestResponse,
  type ModelTestResult,
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
  const catalogState = useAsync(getModelCatalog, []);
  const [draftSecrets, setDraftSecrets] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState<string | null>(null);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<ModelTestResponse | null>(null);
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);
  const credentials = useMemo(
    () => Object.values(settings.models.provider_credentials).sort((a, b) => a.name.localeCompare(b.name)),
    [settings.models.provider_credentials]
  );
  const configuredCount = credentials.filter((credential) => credential.configured).length;
  const catalog = catalogState.data ?? [];
  const filteredCatalog = useMemo(() => filterModelCatalog(catalog, query), [catalog, query]);
  const testResultsByModel = useMemo(() => {
    const results = new Map<string, ModelTestResult>();
    for (const item of testResult?.items ?? []) {
      results.set(modelKey(item.provider, item.model), item);
    }
    return results;
  }, [testResult]);

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

  async function runModelTests() {
    setTesting(true);
    setError(null);
    try {
      setTestResult(await testModels());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setTesting(false);
    }
  }

  return (
    <div className="models-settings">
      <section className="models-hero">
        <div className="models-hero-copy">
          <p className="eyebrow">Models</p>
          <h2>Provider readiness and model catalog</h2>
          <p>
            Configure provider credentials, inspect default and small model coverage, and run
            lightweight connectivity checks from one place.
          </p>
        </div>
        <dl className="models-hero-stats">
          <KeyValue label="Default provider" value={settings.models.default_provider} />
          <KeyValue label="Default model" value={<span className="mono">{settings.models.default_model}</span>} />
          <KeyValue label="Providers configured" value={`${configuredCount}/${credentials.length}`} />
          <KeyValue label="Catalog models" value={catalog.length || "Loading"} />
        </dl>
      </section>

      <ErrorBanner message={error || catalogState.error} />

      <Panel title="Provider Credentials">
        <div className="provider-card-grid">
          {credentials.map((credential) => {
            const hasVaultSecret = credential.updated_at !== null;
            return (
              <article className="provider-card" key={credential.name}>
                <div className="provider-card-heading">
                  <div>
                    <h3>{credential.name}</h3>
                    <p>{credential.source === "none" ? credential.env_var : credential.source}</p>
                  </div>
                  <StatusBadge status={credential.configured ? "configured" : "unconfigured"} />
                </div>
                <dl className="provider-card-meta">
                  <KeyValue label="Source" value={formatCredentialSource(credential.source)} />
                  <KeyValue label="Vault updated" value={formatDate(credential.updated_at)} />
                </dl>
                <Field label="Secret">
                  <input
                    aria-label={`${credential.name} secret`}
                    type="password"
                    value={draftSecrets[credential.name] ?? ""}
                    placeholder={hasVaultSecret ? "Replace vault secret" : "Set vault secret"}
                    onChange={(event) =>
                      setDraftSecrets((current) => ({
                        ...current,
                        [credential.name]: event.target.value
                      }))
                    }
                  />
                </Field>
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
                    disabled={saving === credential.name || !hasVaultSecret}
                    title={
                      hasVaultSecret
                        ? "Clear saved vault credential"
                        : "Environment credential cannot be cleared here"
                    }
                    onClick={() => void clearSecret(credential.name)}
                  >
                    {hasVaultSecret ? "Clear vault" : "Env only"}
                  </button>
                </div>
              </article>
            );
          })}
        </div>
      </Panel>

      <Panel
        title="Catalog"
        actions={
          <div className="models-test-actions">
            {testResult ? <span className="models-test-summary">{formatModelTestSummary(testResult)}</span> : null}
            <button type="button" disabled={testing || catalogState.loading} onClick={() => void runModelTests()}>
              {testing ? "Testing" : "Test models"}
            </button>
          </div>
        }
      >
        <div className="models-catalog-toolbar">
          <Field label="Search">
            <input
              type="search"
              placeholder="Provider, model, or display name"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </Field>
          <span className="subtle">
            {filteredCatalog.length} of {catalog.length || 0} models
          </span>
        </div>
        {catalogState.loading ? <Loading label="Loading model catalog" /> : null}
        {!catalogState.loading && filteredCatalog.length === 0 ? (
          <EmptyState>No models match this search</EmptyState>
        ) : (
          <table className="models-catalog-table">
            <thead>
              <tr>
                <th>Provider</th>
                <th>Model</th>
                <th>Name</th>
                <th>Badges</th>
                <th>Context</th>
                <th>Speed / capabilities</th>
                <th>Test</th>
              </tr>
            </thead>
            <tbody>
              {filteredCatalog.map((model) => (
                <tr key={modelKey(model.provider, model.model)}>
                  <td>{model.provider}</td>
                  <td className="mono">{model.model}</td>
                  <td>{model.display_name}</td>
                  <td>
                    <ModelBadges model={model} />
                  </td>
                  <td>
                    <span className="mono">{formatTokens(model.context_window)}</span>
                    {model.max_output ? (
                      <span className="subtle"> / {formatTokens(model.max_output)} out</span>
                    ) : null}
                  </td>
                  <td>
                    <CapabilityList model={model} />
                  </td>
                  <td>
                    <ModelTestStatus result={testResultsByModel.get(modelKey(model.provider, model.model))} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
    </div>
  );
}

function ModelBadges({ model }: { model: ModelCatalogRow }) {
  const badges = [
    model.is_default ? "default" : null,
    model.is_small ? "small" : null
  ].filter(Boolean);
  if (badges.length === 0) {
    return <span className="subtle">None</span>;
  }
  return (
    <div className="badge-row">
      {badges.map((badge) => (
        <span className="badge" key={badge}>
          {badge}
        </span>
      ))}
    </div>
  );
}

function CapabilityList({ model }: { model: ModelCatalogRow }) {
  const capabilities = [
    model.is_small ? "fast" : "balanced",
    model.supports_tools ? "tools" : null,
    model.supports_vision ? "vision" : null,
    model.supports_reasoning ? "reasoning" : null
  ].filter(Boolean);
  return <span>{capabilities.join(" · ")}</span>;
}

function ModelTestStatus({ result }: { result: ModelTestResult | undefined }) {
  if (!result) {
    return <span className="status status-neutral"><span className="status-dot" />Not tested</span>;
  }
  if (isSkippedModelTest(result)) {
    return <span className="status status-neutral"><span className="status-dot" />Skipped</span>;
  }
  if (result.ok) {
    return (
      <span className="status status-good" title={formatLatency(result.latency_ms)}>
        <span className="status-dot" />
        Pass
      </span>
    );
  }
  return (
    <span className="status status-bad" title={result.error ?? "Model test failed"}>
      <span className="status-dot" />
      Fail
    </span>
  );
}

function filterModelCatalog(catalog: ModelCatalogRow[], query: string): ModelCatalogRow[] {
  const normalized = query.trim().toLowerCase();
  if (!normalized) {
    return catalog;
  }
  return catalog.filter((model) =>
    [model.provider, model.model, model.display_name].some((value) =>
      value.toLowerCase().includes(normalized)
    )
  );
}

function modelKey(provider: string, model: string): string {
  return `${provider}:${model}`;
}

function formatTokens(value: number): string {
  if (value >= 1_000_000) {
    return `${value / 1_000_000}M`;
  }
  if (value >= 1_000) {
    return `${value / 1_000}K`;
  }
  return String(value);
}

function formatLatency(value: number | null): string {
  return value === null ? "Latency unavailable" : `${Math.round(value)} ms`;
}

function formatCredentialSource(source: string): string {
  if (source === "none") {
    return "Not configured";
  }
  return source;
}

function isSkippedModelTest(result: ModelTestResult): boolean {
  return !result.ok && result.error === "Missing provider API key";
}

function formatModelTestSummary(result: ModelTestResponse): string {
  const parts = [`${result.summary.ok} ok`, `${result.summary.failed} failed`];
  if (result.summary.skipped > 0) {
    parts.push(`${result.summary.skipped} skipped`);
  }
  return parts.join(" · ");
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
