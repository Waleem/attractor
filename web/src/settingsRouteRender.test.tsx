import { renderToStaticMarkup } from "react-dom/server";
import { SettingsRouteView } from "./routes/SettingsRoute.js";
import type { ModelCatalogRow, SettingsOverview } from "./api.js";

function assertIncludes(actual: string, expected: string, message: string) {
  if (!actual.includes(expected)) {
    throw new Error(`${message}\nexpected to include: ${expected}\nactual: ${actual}`);
  }
}

function assertNotIncludes(actual: string, unexpected: string, message: string) {
  if (actual.includes(unexpected)) {
    throw new Error(`${message}\nexpected not to include: ${unexpected}\nactual: ${actual}`);
  }
}

function renderSettings(
  settings: SettingsOverview | null,
  options: {
    settingsError?: string | null;
    settingsLoading?: boolean;
    catalog?: ModelCatalogRow[] | null;
    catalogError?: string | null;
    catalogLoading?: boolean;
  } = {}
) {
  return renderToStaticMarkup(
    <SettingsRouteView
      settingsState={{
        data: settings,
        error: options.settingsError ?? null,
        loading: options.settingsLoading ?? false,
        refresh() {},
        setData() {}
      }}
      catalogState={{
        data: options.catalog ?? null,
        error: options.catalogError ?? null,
        loading: options.catalogLoading ?? false,
        refresh() {},
        setData() {}
      }}
    />
  );
}

const settingsPayload: SettingsOverview = {
  models: {
    default_provider: "openai",
    default_model: "gpt-cli-task-4",
    provider_credentials: {
      openai: {
        name: "OpenAI",
        env_var: "OPENAI_API_KEY",
        configured: true,
        updated_at: "2026-07-03T12:00:00Z",
        source: "vault"
      }
    }
  },
  environments: {
    default: "local",
    items: [{ name: "local", mode: "local", description: "Local execution" }]
  },
  variables: {
    items: [{ key: "DEFAULT_REGION", value: "us-west-1", updated_at: "2026-07-03T12:00:00Z" }]
  },
  server: {
    status: "online",
    max_concurrent_runs: 2
  },
  storage: {
    status: "ready"
  },
  monitoring: {
    active_runs: 1,
    event_stream: "enabled"
  },
  pages: [
    {
      id: "models",
      title: "Models",
      description: "Provider model defaults and credentials.",
      groups: [
        {
          title: "Defaults",
          rows: [
            {
              label: "Default provider",
              description: "Provider selected for new runs.",
              value: "openai",
              editability: "editable"
            }
          ]
        }
      ]
    }
  ]
};

const catalogPayload: ModelCatalogRow[] = [
  {
    provider: "openai",
    model: "gpt-cli-task-4",
    display_name: "GPT CLI Task 4",
    context_window: 128000,
    max_output: 4096,
    supports_tools: true,
    supports_vision: false,
    supports_reasoning: true,
    is_default: true,
    is_small: false
  }
];

const fullMarkup = renderSettings(settingsPayload, { catalog: catalogPayload });
assertIncludes(fullMarkup, "Models", "settings renders the API-shaped models page");
assertIncludes(fullMarkup, "GPT CLI Task 4", "settings renders model catalog rows");
assertIncludes(fullMarkup, "configured", "settings renders provider credential status");

const errorMarkup = renderSettings(null, {
  settingsError: "settings service unavailable",
  catalog: []
});
assertIncludes(errorMarkup, "settings service unavailable", "settings fetch errors are visible");
assertIncludes(errorMarkup, "Settings data is not available", "settings fetch errors show a contained empty state");

const partialPayload = {
  ...settingsPayload,
  models: {
    default_provider: "",
    default_model: ""
  },
  variables: {},
  pages: [
    {
      id: "models",
      title: "Models",
      description: "Provider model defaults and credentials."
    }
  ]
} as unknown as SettingsOverview;
const partialMarkup = renderSettings(partialPayload, {
  catalog: undefined as unknown as ModelCatalogRow[],
  catalogError: "catalog unavailable"
});
assertIncludes(partialMarkup, "catalog unavailable", "catalog fetch errors are visible");
assertIncludes(partialMarkup, "No settings rows are available", "missing page groups render an empty state");
assertNotIncludes(partialMarkup, "<table", "missing catalog data does not render an empty catalog table");
