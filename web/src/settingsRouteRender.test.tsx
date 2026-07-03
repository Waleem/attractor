import type { ModelCatalogRow, SettingsOverview } from "./api.js";

type FetchHandler = (path: string) => {
  ok?: boolean;
  status?: number;
  body: unknown;
};

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
  const { document } = installMiniDom();
  const fetchCalls: string[] = [];
  globalThis.fetch = ((input: RequestInfo | URL) => {
    const path = String(input);
    fetchCalls.push(path);
    const result = handler(path);
    return Promise.resolve({
      ok: result.ok ?? true,
      status: result.status ?? (result.ok === false ? 500 : 200),
      text: () => Promise.resolve(JSON.stringify(result.body))
    } as Response);
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
  const markup = container.innerHTML;
  root.unmount();
  return { markup, fetchCalls };
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

function installMiniDom() {
  const document = new MiniDocument();
  const window = {
    document,
    location: { pathname: "/settings" },
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
    Event: class {}
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
    Text: MiniText
  })) {
    Object.defineProperty(globalThis, name, {
      configurable: true,
      value,
      writable: true
    });
  }
  return { document, window };
}

class MiniNode {
  parentNode: MiniNode | null = null;
  childNodes: MiniNode[] = [];
  ownerDocument: MiniDocument;

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

  addEventListener() {}
  removeEventListener() {}
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

async function main() {
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
}

void main();
