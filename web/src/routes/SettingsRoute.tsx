import { useMemo, useState, type ReactNode } from "react";
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
  type SettingsOverview,
  type SettingsPage,
  type SettingsPageGroup,
  type SettingsPageRow
} from "../api";
import { useAsync, type AsyncState } from "../components/useAsync";
import {
  EmptyState,
  ErrorBanner,
  Field,
  Loading,
  PageHeader,
  SectionCard,
  SettingsRow,
  StatusBadge,
  formatDate
} from "../components/ui";

const settingsNavigation = [
  {
    label: "General",
    pages: [
      { id: "models", label: "Models" },
      { id: "integrations", label: "Integrations" },
      { id: "sandboxes", label: "Sandboxes" }
    ]
  },
  {
    label: "Workflows",
    pages: [
      { id: "environments", label: "Environments" },
      { id: "variables", label: "Variables" },
      { id: "secrets", label: "Secrets" },
      { id: "run-defaults", label: "Run defaults" }
    ]
  },
  {
    label: "Administration",
    pages: [
      { id: "server", label: "Server" },
      { id: "security", label: "Security" },
      { id: "storage", label: "Storage" },
      { id: "monitoring", label: "Monitoring" }
    ]
  },
  {
    label: "Events",
    pages: [{ id: "live-events", label: "Live events" }]
  }
];

export function SettingsRoute() {
  const settingsState = useAsync(getSettings, []);
  const catalogState = useAsync(getModelCatalog, []);

  return <SettingsRouteView settingsState={settingsState} catalogState={catalogState} />;
}

export function SettingsRouteView({
  settingsState,
  catalogState
}: {
  settingsState: AsyncState<SettingsOverview>;
  catalogState: AsyncState<ModelCatalogRow[]>;
}) {
  const [activePageId, setActivePageId] = useState("models");
  const settings = settingsState.data;
  const pages = safeArray(settings?.pages);
  const pagesById = useMemo(() => {
    const map = new Map<string, SettingsPage>();
    for (const page of pages) {
      if (page?.id) {
        map.set(page.id, page);
      }
    }
    return map;
  }, [pages]);
  const activePage = pagesById.get(activePageId) ?? pages[0] ?? null;
  const showUnavailableState = !settingsState.loading && !settings;
  const showEmptyPagesState = !settingsState.loading && settings && !activePage;

  return (
    <>
      <PageHeader title="Settings" />
      <ErrorBanner message={settingsState.error} />
      {settingsState.loading ? <Loading /> : null}
      {showUnavailableState ? <EmptyState>Settings data is not available</EmptyState> : null}
      {showEmptyPagesState ? <EmptyState>No settings pages are available</EmptyState> : null}
      {settings && activePage ? (
        <div className="settings-layout">
          <SettingsSubnav
            activePageId={activePage.id}
            availablePages={pagesById}
            onChange={setActivePageId}
          />
          <SettingsPageTemplate page={activePage}>
            {activePage.id === "models" ? (
              <ModelCatalogSection settings={settings} catalogState={catalogState} />
            ) : null}
            {activePage.id === "variables" ? (
              <VariablesEditor settings={settings} refresh={settingsState.refresh} />
            ) : null}
            {activePage.id === "secrets" ? (
              <SecretsEditor settings={settings} refresh={settingsState.refresh} />
            ) : null}
          </SettingsPageTemplate>
        </div>
      ) : null}
    </>
  );
}

function SettingsSubnav({
  activePageId,
  availablePages,
  onChange
}: {
  activePageId: string;
  availablePages: Map<string, SettingsPage>;
  onChange: (pageId: string) => void;
}) {
  return (
    <aside className="settings-subnav" aria-label="Settings sections">
      {settingsNavigation.map((group) => (
        <section key={group.label}>
          <h2>{group.label}</h2>
          {group.pages.map((page) => (
            <button
              key={page.id}
              type="button"
              className={activePageId === page.id ? "active" : ""}
              disabled={!availablePages.has(page.id)}
              onClick={() => onChange(page.id)}
            >
              {page.label}
            </button>
          ))}
        </section>
      ))}
    </aside>
  );
}

function SettingsPageTemplate({
  page,
  children
}: {
  page: SettingsPage;
  children?: ReactNode;
}) {
  const groups = safeArray<SettingsPageGroup>(page.groups);
  return (
    <main className="settings-page">
      <header className="settings-page-header">
        <p className="eyebrow">Settings</p>
        <h2>{page.title}</h2>
        <p>{page.description}</p>
      </header>
      <div className="settings-groups">
        {groups.length === 0 ? <EmptyState>No settings rows are available</EmptyState> : null}
        {groups.map((group) => (
          <SectionCard title={group.title} key={`${page.id}:${group.title}`}>
            <dl className="settings-row-list">
              {safeArray<SettingsPageRow>(group.rows).map((row) => (
                <SettingsRow
                  key={`${row.label}:${row.description}`}
                  label={row.label}
                  description={row.description}
                  value={formatSettingsValue(row)}
                  editability={row.editability}
                />
              ))}
            </dl>
          </SectionCard>
        ))}
      </div>
      {children ? <div className="settings-page-actions">{children}</div> : null}
    </main>
  );
}

function ModelCatalogSection({
  settings,
  catalogState
}: {
  settings: SettingsOverview;
  catalogState: AsyncState<ModelCatalogRow[]>;
}) {
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<ModelTestResponse | null>(null);
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);
  const catalog = safeArray<ModelCatalogRow>(catalogState.data);
  const providerCredentials = settings.models?.provider_credentials ?? {};
  const filteredCatalog = useMemo(() => filterModelCatalog(catalog, query), [catalog, query]);
  const testResultsByModel = useMemo(() => {
    const results = new Map<string, ModelTestResult>();
    for (const item of testResult?.items ?? []) {
      results.set(modelKey(item.provider, item.model), item);
    }
    return results;
  }, [testResult]);

  async function runModelTests() {
    setTesting(true);
    setError(null);
    setTestResult(null);
    try {
      setTestResult(await testModels());
    } catch (caught) {
      setTestResult(null);
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setTesting(false);
    }
  }

  return (
    <SectionCard
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
      <ErrorBanner message={error || catalogState.error} />
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
      {!catalogState.loading && catalog.length === 0 ? (
        <EmptyState>{catalogState.error ? "Model catalog is not available" : "No models are available"}</EmptyState>
      ) : !catalogState.loading && filteredCatalog.length === 0 ? (
        <EmptyState>No models match this search</EmptyState>
      ) : (
        <div className="models-catalog-scroll">
          <table className="models-catalog-table">
            <thead>
              <tr>
                <th>Provider</th>
                <th>Configured</th>
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
                  <td>
                    <StatusBadge
                      status={
                        providerCredentials[model.provider]?.configured
                          ? "configured"
                          : "unconfigured"
                      }
                    />
                  </td>
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
        </div>
      )}
    </SectionCard>
  );
}

function VariablesEditor({
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

  const variables = safeArray(settings.variables?.items);

  return (
    <SectionCard title="Edit Variables">
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
      {variables.length === 0 ? (
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
            {variables.map((variable) => (
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
    </SectionCard>
  );
}

function SecretsEditor({
  settings,
  refresh
}: {
  settings: SettingsOverview;
  refresh: () => void;
}) {
  const [draftSecrets, setDraftSecrets] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const providerCredentials = settings.models?.provider_credentials ?? {};
  const credentials = useMemo(
    () => Object.values(providerCredentials).sort((a, b) => a.name.localeCompare(b.name)),
    [providerCredentials]
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
    <SectionCard title="Edit Secrets">
      <ErrorBanner message={error} />
      <div className="provider-card-grid">
        {credentials.map((credential) => {
          const hasVaultSecret = credential.updated_at !== null;
          const saveLabel = `Save ${credential.name} secret`;
          const clearLabel = hasVaultSecret
            ? `Clear ${credential.name} vault secret`
            : `${credential.name} has no vault secret to clear`;
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
                <div className="key-value">
                  <dt>Source</dt>
                  <dd>{formatCredentialSource(credential.source)}</dd>
                </div>
                <div className="key-value">
                  <dt>Vault updated</dt>
                  <dd>{formatDate(credential.updated_at)}</dd>
                </div>
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
                  aria-label={saveLabel}
                  disabled={saving === credential.name}
                  title={saveLabel}
                  onClick={() => void saveSecret(credential.name)}
                >
                  Save
                </button>
                <button
                  className="secondary"
                  type="button"
                  aria-label={clearLabel}
                  disabled={saving === credential.name || !hasVaultSecret}
                  title={clearLabel}
                  onClick={() => void clearSecret(credential.name)}
                >
                  {hasVaultSecret ? "Clear vault" : "Env only"}
                </button>
              </div>
            </article>
          );
        })}
      </div>
    </SectionCard>
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

function formatSettingsValue(row: SettingsPageRow): string {
  if (row.value === null || row.value === "") {
    return "None";
  }
  if (typeof row.value === "boolean") {
    return row.value ? "Enabled" : "Disabled";
  }
  return String(row.value);
}

function filterModelCatalog(catalog: ModelCatalogRow[], query: string): ModelCatalogRow[] {
  const normalized = query.trim().toLowerCase();
  if (!normalized) {
    return catalog;
  }
  return catalog.filter((model) =>
    [model.provider, model.model, model.display_name].some((value) =>
      String(value ?? "").toLowerCase().includes(normalized)
    )
  );
}

function modelKey(provider: string, model: string): string {
  return `${provider}:${model}`;
}

function formatTokens(value: number | null | undefined): string {
  if (typeof value !== "number") {
    return "None";
  }
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

function safeArray<T>(value: T[] | null | undefined): T[] {
  return Array.isArray(value) ? value : [];
}
