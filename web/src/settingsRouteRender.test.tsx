import type { ModelCatalogRow, SettingsOverview } from "./api.js";

type FetchResult = {
  ok?: boolean;
  status?: number;
  body: unknown;
};
type FetchHandler = (path: string, init?: RequestInit) => FetchResult | Promise<FetchResult>;

function assertIncludes(actual: string, expected: string, message: string) {
  if (!actual.includes(expected)) {
    throw new Error(`${message}\nexpected to include: ${expected}\nactual: ${actual}`);
  }
}

function assertEqual(actual: unknown, expected: unknown, message: string) {
  if (actual !== expected) {
    throw new Error(`${message}\nexpected: ${String(expected)}\nactual:   ${String(actual)}`);
  }
}

async function renderSettingsRoute(handler: FetchHandler): Promise<{
  markup: string;
  fetchCalls: string[];
}> {
  const { container, fetchCalls, root } = await mountSettingsRoute(handler);
  const markup = container.innerHTML;
  root.unmount();
  return { markup, fetchCalls };
}

async function mountSettingsRoute(handler: FetchHandler): Promise<{
  container: MiniElement;
  fetchCalls: string[];
  root: { unmount(): void };
}> {
  const { document } = installMiniDom("/settings");
  const fetchCalls: string[] = [];
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    fetchCalls.push(path);
    const result = await handler(path, init);
    return {
      ok: result.ok ?? true,
      status: result.status ?? (result.ok === false ? 500 : 200),
      text: () => Promise.resolve(JSON.stringify(result.body))
    } as Response;
  }) as typeof fetch;

  const [{ createRoot }, { SettingsRoute }] = await Promise.all([
    import("react-dom/client"),
    import("./routes/SettingsRoute.js")
  ]);
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container as unknown as Element);
  root.render(<SettingsRoute />);

  await waitFor(() => fetchCalls.length >= 2);
  await waitFor(() => !container.textContent.includes("Loading"));
  return { container, fetchCalls, root };
}

async function renderAppRoute(
  pathname: string,
  handler: FetchHandler,
  expectedFetchCalls = 2
): Promise<{
  markup: string;
  fetchCalls: string[];
}> {
  const { document } = installMiniDom(pathname);
  const fetchCalls: string[] = [];
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    fetchCalls.push(path);
    const result = await handler(path, init);
    return {
      ok: result.ok ?? true,
      status: result.status ?? (result.ok === false ? 500 : 200),
      text: () => Promise.resolve(JSON.stringify(result.body))
    } as Response;
  }) as typeof fetch;

  const [{ createRoot }, { default: App }] = await Promise.all([
    import("react-dom/client"),
    import("./App.js")
  ]);
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container as unknown as Element);
  root.render(<App />);

  if (expectedFetchCalls > 0) {
    await waitFor(() => fetchCalls.length >= expectedFetchCalls);
    await waitFor(() => !container.textContent.includes("Loading"));
  } else {
    await waitFor(() => container.textContent.length > 0);
  }
  const markup = container.innerHTML;
  root.unmount();
  return { markup, fetchCalls };
}

async function mountAppRoute(
  pathname: string,
  handler: FetchHandler
): Promise<{
  container: MiniElement;
  fetchCalls: string[];
  root: { unmount(): void };
}> {
  const { document } = installMiniDom(pathname);
  const fetchCalls: string[] = [];
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    fetchCalls.push(path);
    const result = await handler(path, init);
    return {
      ok: result.ok ?? true,
      status: result.status ?? (result.ok === false ? 500 : 200),
      text: () => Promise.resolve(JSON.stringify(result.body))
    } as Response;
  }) as typeof fetch;

  const [{ createRoot }, { default: App }] = await Promise.all([
    import("react-dom/client"),
    import("./App.js")
  ]);
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container as unknown as Element);
  root.render(<App />);

  await waitFor(() => fetchCalls.length >= 1);
  await waitFor(() => !container.textContent.includes("Loading"));
  return { container, fetchCalls, root };
}

async function waitFor(assertion: () => boolean) {
  const startedAt = Date.now();
  while (!assertion()) {
    if (Date.now() - startedAt > 1000) {
      throw new Error("Timed out waiting for route render");
    }
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
}

function installMiniDom(pathname = "/settings") {
  const document = new MiniDocument();
  const location = { pathname };
  const window = {
    document,
    location,
    history: {
      pushState(_state: unknown, _title: string, nextPath: string) {
        location.pathname = nextPath;
      }
    },
    navigator: { userAgent: "node" },
    addEventListener() {},
    removeEventListener() {},
    getComputedStyle() {
      return {};
    },
    HTMLIFrameElement: MiniElement,
    HTMLElement: MiniElement,
    HTMLInputElement: MiniElement,
    Node: MiniNode,
    Text: MiniText,
    Event: MiniEvent
  };
  document.defaultView = window;
  for (const [name, value] of Object.entries({
    window,
    document,
    navigator: window.navigator,
    HTMLElement: MiniElement,
    HTMLInputElement: MiniElement,
    HTMLIFrameElement: MiniElement,
    Node: MiniNode,
    Text: MiniText,
    Event: MiniEvent
  })) {
    Object.defineProperty(globalThis, name, {
      configurable: true,
      value,
      writable: true
    });
  }
  return { document, window };
}

class MiniEvent {
  currentTarget: MiniNode | null = null;
  target: MiniNode | null = null;
  defaultPrevented = false;
  propagationStopped = false;
  readonly timeStamp = Date.now();

  constructor(
    public readonly type: string,
    public readonly options: { bubbles?: boolean; cancelable?: boolean } = {}
  ) {}

  get bubbles(): boolean {
    return this.options.bubbles ?? false;
  }

  get cancelable(): boolean {
    return this.options.cancelable ?? false;
  }

  preventDefault() {
    if (this.cancelable) {
      this.defaultPrevented = true;
    }
  }

  stopPropagation() {
    this.propagationStopped = true;
  }
}

type MiniEventListener = ((event: MiniEvent) => void) | { handleEvent(event: MiniEvent): void };

class MiniNode {
  parentNode: MiniNode | null = null;
  childNodes: MiniNode[] = [];
  ownerDocument: MiniDocument;
  private readonly eventListeners = new Map<string, Set<MiniEventListener>>();

  constructor(
    public readonly nodeType: number,
    public readonly nodeName: string,
    ownerDocument?: MiniDocument
  ) {
    this.ownerDocument = ownerDocument ?? (this as unknown as MiniDocument);
  }

  get firstChild(): MiniNode | null {
    return this.childNodes[0] ?? null;
  }

  get lastChild(): MiniNode | null {
    return this.childNodes.at(-1) ?? null;
  }

  get textContent(): string {
    return this.childNodes.map((child) => child.textContent).join("");
  }

  set textContent(value: string) {
    this.childNodes = value ? [this.ownerDocument.createTextNode(value)] : [];
    for (const child of this.childNodes) {
      child.parentNode = this;
    }
  }

  appendChild<T extends MiniNode>(node: T): T {
    node.parentNode?.removeChild(node);
    node.parentNode = this;
    this.childNodes.push(node);
    return node;
  }

  insertBefore<T extends MiniNode>(node: T, before: MiniNode | null): T {
    node.parentNode?.removeChild(node);
    node.parentNode = this;
    if (!before) {
      this.childNodes.push(node);
      return node;
    }
    const index = this.childNodes.indexOf(before);
    if (index === -1) {
      this.childNodes.push(node);
    } else {
      this.childNodes.splice(index, 0, node);
    }
    return node;
  }

  removeChild<T extends MiniNode>(node: T): T {
    const index = this.childNodes.indexOf(node);
    if (index !== -1) {
      this.childNodes.splice(index, 1);
      node.parentNode = null;
    }
    return node;
  }

  contains(node: MiniNode | null): boolean {
    if (!node) {
      return false;
    }
    if (node === this) {
      return true;
    }
    return this.childNodes.some((child) => child.contains(node));
  }

  addEventListener(type: string, listener: MiniEventListener | null) {
    if (!listener) {
      return;
    }
    const listeners = this.eventListeners.get(type) ?? new Set<MiniEventListener>();
    listeners.add(listener);
    this.eventListeners.set(type, listeners);
  }

  removeEventListener(type: string, listener: MiniEventListener | null) {
    if (!listener) {
      return;
    }
    this.eventListeners.get(type)?.delete(listener);
  }

  dispatchEvent(event: MiniEvent): boolean {
    if (!event.target) {
      event.target = this;
    }
    event.currentTarget = this;
    for (const listener of this.eventListeners.get(event.type) ?? []) {
      if (typeof listener === "function") {
        listener(event);
      } else {
        listener.handleEvent(event);
      }
    }
    if (event.bubbles && !event.propagationStopped && this.parentNode) {
      this.parentNode.dispatchEvent(event);
    }
    return !event.defaultPrevented;
  }
}

class MiniText extends MiniNode {
  constructor(public data: string, ownerDocument: MiniDocument) {
    super(3, "#text", ownerDocument);
  }

  get nodeValue(): string {
    return this.data;
  }

  set nodeValue(value: string) {
    this.data = value;
  }

  override get textContent(): string {
    return this.data;
  }

  override set textContent(value: string) {
    this.data = value;
  }
}

class MiniElement extends MiniNode {
  readonly attributes = new Map<string, string>();
  readonly style: Record<string, string> = {};
  namespaceURI = "http://www.w3.org/1999/xhtml";
  value = "";
  checked = false;
  disabled = false;

  constructor(public readonly tagName: string, ownerDocument: MiniDocument) {
    super(1, tagName.toUpperCase(), ownerDocument);
  }

  get localName(): string {
    return this.tagName.toLowerCase();
  }

  get innerHTML(): string {
    return this.childNodes.map((child) => serializeNode(child)).join("");
  }

  set innerHTML(value: string) {
    this.textContent = value;
  }

  get className(): string {
    return this.getAttribute("class") ?? "";
  }

  set className(value: string) {
    this.setAttribute("class", value);
  }

  getAttribute(name: string): string | null {
    return this.attributes.get(name) ?? null;
  }

  setAttribute(name: string, value: string) {
    this.attributes.set(name, String(value));
  }

  removeAttribute(name: string) {
    this.attributes.delete(name);
  }

  hasAttribute(name: string): boolean {
    return this.attributes.has(name);
  }

  click() {
    if (!this.disabled) {
      this.dispatchEvent(new MiniEvent("click", { bubbles: true, cancelable: true }));
    }
  }

  focus() {}
  blur() {}
}

class MiniDocument extends MiniNode {
  documentElement: MiniElement;
  body: MiniElement;
  activeElement: MiniElement | null = null;
  defaultView: unknown = null;

  constructor() {
    super(9, "#document");
    this.ownerDocument = this;
    this.documentElement = new MiniElement("html", this);
    this.body = new MiniElement("body", this);
    this.documentElement.appendChild(this.body);
    this.appendChild(this.documentElement);
  }

  createElement(tagName: string): MiniElement {
    return new MiniElement(tagName, this);
  }

  createElementNS(_namespace: string, tagName: string): MiniElement {
    return new MiniElement(tagName, this);
  }

  createTextNode(text: string): MiniText {
    return new MiniText(text, this);
  }

  createComment(text: string): MiniText {
    return new MiniText(text, this);
  }

  querySelector(_selector: string): MiniElement | null {
    return null;
  }
}

function serializeNode(node: MiniNode): string {
  if (node.nodeType === 3) {
    return escapeHtml(node.textContent);
  }
  if (!(node instanceof MiniElement)) {
    return node.childNodes.map((child) => serializeNode(child)).join("");
  }
  const attrs = Array.from(node.attributes.entries())
    .map(([name, value]) => ` ${name}="${escapeHtml(value)}"`)
    .join("");
  return `<${node.localName}${attrs}>${node.innerHTML}</${node.localName}>`;
}

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function findButtonByText(container: MiniElement, label: string): MiniElement {
  const button = findElement(
    container,
    (element) => element.localName === "button" && element.textContent.trim() === label
  );
  if (!button) {
    throw new Error(`Button not found: ${label}\nactual: ${container.innerHTML}`);
  }
  return button;
}

function findInputByLabel(container: MiniElement, label: string): MiniElement {
  const field = findElement(
    container,
    (element) => element.localName === "label" && element.textContent.includes(label)
  );
  if (!field) {
    throw new Error(`Input label not found: ${label}\nactual: ${container.innerHTML}`);
  }
  const input = findElement(field, (element) => element.localName === "input");
  if (!input) {
    throw new Error(`Input not found for label: ${label}\nactual: ${container.innerHTML}`);
  }
  return input;
}

function setInputValue(input: MiniElement, value: string) {
  input.value = value;
  input.dispatchEvent(new MiniEvent("input", { bubbles: true, cancelable: true }));
  input.dispatchEvent(new MiniEvent("change", { bubbles: true, cancelable: true }));
}

function findElement(node: MiniNode, predicate: (element: MiniElement) => boolean): MiniElement | null {
  if (node instanceof MiniElement && predicate(node)) {
    return node;
  }
  for (const child of node.childNodes) {
    const match = findElement(child, predicate);
    if (match) {
      return match;
    }
  }
  return null;
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
    },
    {
      id: "server",
      title: "Server",
      description: "Server runtime settings.",
      groups: [
        {
          title: "Runtime",
          rows: [
            {
              label: "Status",
              description: "Server process status.",
              value: "online",
              editability: "read-only"
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

async function main() {
  const settingsHandler = (path: string) => {
    if (path === "/api/settings") {
      return { body: settingsPayload };
    }
    if (path === "/api/settings/models/catalog") {
      return { body: { items: catalogPayload } };
    }
    throw new Error(`Unexpected fetch ${path}`);
  };

  const modelsRouteResult = await renderAppRoute("/settings/models", settingsHandler);
  assertIncludes(modelsRouteResult.markup, "GPT CLI Task 4", "/settings/models renders the settings models page");
  assertEqual(
    modelsRouteResult.fetchCalls.includes("/api/settings"),
    true,
    "/settings/models calls getSettings"
  );

  const serverRouteResult = await renderAppRoute("/settings/server", settingsHandler);
  assertIncludes(serverRouteResult.markup, "Server runtime settings.", "/settings/server renders the server page");
  assertIncludes(serverRouteResult.markup, "Server process status.", "/settings/server renders server settings rows");

  const invalidRouteResult = await renderAppRoute(
    "/settings/not-a-page",
    (path) => {
      throw new Error(`Unexpected fetch ${path}`);
    },
    0
  );
  assertIncludes(
    invalidRouteResult.markup,
    "No route for /settings/not-a-page",
    "invalid settings subpages render the app not-found route"
  );
  assertEqual(invalidRouteResult.fetchCalls.length, 0, "invalid settings subpages do not load settings data");

  let resolveModelTest: (result: FetchResult) => void = () => undefined;
  const pendingModelTest = new Promise<FetchResult>((resolve) => {
    resolveModelTest = resolve;
  });
  const modelTestResult = await mountSettingsRoute((path) => {
    if (path === "/api/settings") {
      return { body: settingsPayload };
    }
    if (path === "/api/settings/models/catalog") {
      return { body: { items: catalogPayload } };
    }
    if (path === "/api/settings/models/test") {
      return pendingModelTest;
    }
    throw new Error(`Unexpected fetch ${path}`);
  });
  findButtonByText(modelTestResult.container, "Test models").click();
  await waitFor(() => modelTestResult.fetchCalls.includes("/api/settings/models/test"));
  await waitFor(() => modelTestResult.container.textContent.includes("Testing"));
  assertIncludes(
    modelTestResult.container.textContent,
    "Testing… 0/1",
    "model testing shows deterministic in-progress count while the test request is pending"
  );
  assertIncludes(
    modelTestResult.container.innerHTML,
    "models-test-spinner",
    "model testing shows a spinner while the test request is pending"
  );
  resolveModelTest({
    body: {
      summary: { ok: 1, failed: 0, skipped: 0, tested_at: "2026-07-03T12:00:00Z" },
      items: [
        {
          provider: "openai",
          model: "gpt-cli-task-4",
          display_name: "GPT CLI Task 4",
          ok: true,
          latency_ms: 42,
          error: null
        }
      ]
    }
  });
  await waitFor(() => modelTestResult.container.textContent.includes("1 ok"));
  modelTestResult.root.unmount();

  const happyResult = await renderSettingsRoute((path) => {
    if (path === "/api/settings") {
      return { body: settingsPayload };
    }
    if (path === "/api/settings/models/catalog") {
      return { body: { items: catalogPayload } };
    }
    throw new Error(`Unexpected fetch ${path}`);
  });
  assertIncludes(happyResult.markup, "GPT CLI Task 4", "settings route renders catalog rows from fetch");
  assertIncludes(happyResult.markup, "configured", "settings route renders provider credential status from fetch");
  assertEqual(happyResult.fetchCalls.includes("/api/settings"), true, "settings route calls getSettings");
  assertEqual(
    happyResult.fetchCalls.includes("/api/settings/models/catalog"),
    true,
    "settings route calls getModelCatalog"
  );

  const failingResult = await renderSettingsRoute((path) => ({
    ok: false,
    status: 503,
    body: { error: path === "/api/settings" ? "settings service unavailable" : "catalog unavailable" }
  }));
  assertIncludes(failingResult.markup, "settings service unavailable", "settings fetch errors are visible");
  assertIncludes(
    failingResult.markup,
    "Settings data is not available",
    "settings fetch errors show a contained empty state"
  );
  assertEqual(failingResult.fetchCalls.includes("/api/settings"), true, "failing route calls getSettings");
  assertEqual(
    failingResult.fetchCalls.includes("/api/settings/models/catalog"),
    true,
    "failing route calls getModelCatalog"
  );

  const partialSettingsPayload = {
    ...settingsPayload,
    models: {
      default_provider: "",
      default_model: ""
    },
    variables: {},
    pages: [
      {
        id: "secrets",
        title: "Secrets",
        description: "Write-only provider secrets.",
        groups: []
      }
    ]
  } as unknown as SettingsOverview;
  const partialResult = await renderSettingsRoute((path) => {
    if (path === "/api/settings") {
      return { body: partialSettingsPayload };
    }
    if (path === "/api/settings/models/catalog") {
      return { body: { items: [] } };
    }
    throw new Error(`Unexpected fetch ${path}`);
  });
  assertIncludes(partialResult.markup, "No settings rows are available", "missing page groups render an empty state");
  assertIncludes(
    partialResult.markup,
    "No provider credentials are available",
    "missing provider credentials render an empty state"
  );

  const reposRouteResult = await mountAppRoute("/repos", (path, init) => {
    if (path === "/api/fs/browse?mode=registration") {
      return {
        body: {
          path: "/workspace",
          roots: ["/workspace"],
          items: [
            {
              name: "sample-repo",
              path: "/workspace/sample-repo",
              kind: "directory",
              is_git_repo: true
            }
          ],
          truncated: false
        }
      };
    }
    if (path === "/api/repos" && init?.method === "POST") {
      return {
        body: {
          id: "repo-1",
          name: "Custom Name",
          local_path: "/workspace/sample-repo",
          default_branch: "main",
          current_commit: "abc123",
          dirty_state: "clean",
          project_config_status: "valid",
          created_at: null,
          updated_at: null,
          last_indexed_at: null
        }
      };
    }
    if (path === "/api/repos") {
      return { body: { items: [] } };
    }
    throw new Error(`Unexpected fetch ${path}`);
  });
  assertIncludes(
    reposRouteResult.container.innerHTML,
    "Choose a folder to register",
    "repos route browser hint supports first-time registration"
  );
  const nameInput = findInputByLabel(reposRouteResult.container, "Name");
  setInputValue(nameInput, "Custom Name");
  findButtonByText(reposRouteResult.container, "Browse").click();
  await waitFor(() => reposRouteResult.fetchCalls.includes("/api/fs/browse?mode=registration"));
  await waitFor(() => reposRouteResult.container.textContent.includes("sample-repo"));
  reposRouteResult.root.unmount();

  const { registrationNameForSelection } = await import("./routes/ReposRoute.js");
  assertEqual(
    registrationNameForSelection("Custom Name", {
      name: "sample-repo",
      path: "/workspace/sample-repo",
      kind: "directory",
      is_git_repo: true
    }),
    "Custom Name",
    "using a repo keeps an existing typed name"
  );
  assertEqual(
    registrationNameForSelection("", {
      name: "sample-repo",
      path: "/workspace/sample-repo",
      kind: "directory",
      is_git_repo: true
    }),
    "sample-repo",
    "using a repo fills the name when it is empty"
  );

  const reposRouteNavigationResult = await mountAppRoute("/repos", (path) => {
    if (path === "/api/repos") {
      return {
        body: {
          items: [
            {
              id: "repo-1",
              name: "Registered Repo",
              local_path: "/registered/repo",
              default_branch: "main",
              current_commit: "abc123",
              dirty_state: "clean",
              project_config_status: "valid",
              created_at: null,
              updated_at: null,
              last_indexed_at: null
            }
          ]
        }
      };
    }
    if (path === "/api/fs/browse?mode=registration") {
      return {
        body: {
          path: "/workspace",
          roots: ["/workspace"],
          items: [
            {
              name: "outside",
              path: "/workspace/outside",
              kind: "directory",
              is_git_repo: false
            }
          ],
          truncated: false
        }
      };
    }
    if (path === "/api/fs/browse?path=%2Fworkspace%2Foutside&mode=registration") {
      return {
        body: {
          path: "/workspace/outside",
          roots: ["/workspace"],
          items: [
            {
              name: "inner",
              path: "/workspace/outside/inner",
              kind: "directory",
              is_git_repo: false
            }
          ],
          truncated: false
        }
      };
    }
    if (path === "/api/fs/browse?path=%2Fworkspace%2Fmanual&mode=registration") {
      return {
        body: {
          path: "/workspace/manual",
          roots: ["/workspace"],
          items: [],
          truncated: false
        }
      };
    }
    throw new Error(`Unexpected fetch ${path}`);
  });
  findButtonByText(reposRouteNavigationResult.container, "Browse").click();
  await waitFor(() =>
    reposRouteNavigationResult.fetchCalls.includes("/api/fs/browse?mode=registration")
  );
  await waitFor(() => reposRouteNavigationResult.container.textContent.includes("outside"));
  findButtonByText(reposRouteNavigationResult.container, "Open").click();
  await waitFor(() =>
    reposRouteNavigationResult.fetchCalls.includes(
      "/api/fs/browse?path=%2Fworkspace%2Foutside&mode=registration"
    )
  );
  reposRouteNavigationResult.root.unmount();

  const helperFetchCalls: string[] = [];
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    helperFetchCalls.push(String(input));
    return {
      ok: true,
      status: 200,
      text: () =>
        Promise.resolve(
          JSON.stringify({
            path: "/workspace/manual",
            roots: ["/workspace"],
            items: [],
            truncated: false
          })
        )
    } as Response;
  }) as typeof fetch;
  const { browseRegistrationFilesystem } = await import("./routes/ReposRoute.js");
  await browseRegistrationFilesystem("/workspace/manual");
  assertEqual(
    helperFetchCalls.includes("/api/fs/browse?path=%2Fworkspace%2Fmanual&mode=registration"),
    true,
    "typed registration browsing keeps registration mode"
  );
}

void main();
