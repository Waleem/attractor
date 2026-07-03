import {
  applyGraphHighlightClassesToTargets,
  buildGraphHighlightState,
  type GraphHighlightClassTarget
} from "./graphHighlight.js";
import {
  applyGraphHighlightsToRenderedSvg,
  buildThemedGraphDot,
  graphLayoutKey,
  shouldRenderGraphLayout,
  type GraphViewerUpdateInput
} from "./graphViewerController.js";
import type { RunEvent, WorkflowGraph } from "./api";
import { Graphviz } from "@hpcc-js/wasm";

function assertDeepEqual(actual: unknown, expected: unknown, message: string) {
  const actualJson = JSON.stringify(actual);
  const expectedJson = JSON.stringify(expected);
  if (actualJson !== expectedJson) {
    throw new Error(`${message}\nexpected: ${expectedJson}\nactual:   ${actualJson}`);
  }
}

function mapEntries(map: Map<string, string[]>) {
  return Array.from(map.entries()).sort(([left], [right]) => left.localeCompare(right));
}

function target(
  kind: GraphHighlightClassTarget["kind"],
  id: string | null,
  initialClasses: string[] = []
): GraphHighlightClassTarget & { classNames: Set<string> } {
  const classNames = new Set(initialClasses);
  return {
    kind,
    id,
    classNames,
    addClass(className: string) {
      classNames.add(className);
    },
    removeClass(className: string) {
      classNames.delete(className);
    }
  };
}

class SvgTitleFixture {
  constructor(public textContent: string) {}
}

class SvgGroupFixture {
  private attributes = new Map<string, string>();
  public readonly classNames: Set<string>;
  public readonly classList: {
    add: (className: string) => void;
    remove: (className: string) => void;
    contains: (className: string) => boolean;
  };

  constructor(
    public readonly kind: "node" | "edge",
    public readonly titleText: string,
    classNames: string[]
  ) {
    this.classNames = new Set(classNames);
    this.classList = {
      add: (className: string) => this.classNames.add(className),
      remove: (className: string) => this.classNames.delete(className),
      contains: (className: string) => this.classNames.has(className)
    };
  }

  querySelector(selector: string): SvgTitleFixture | null {
    return selector === "title" ? new SvgTitleFixture(this.titleText) : null;
  }

  getAttribute(name: string): string | null {
    return this.attributes.get(name) ?? null;
  }

  setAttribute(name: string, value: string) {
    this.attributes.set(name, value);
  }
}

class SvgRootFixture {
  constructor(public readonly groups: SvgGroupFixture[]) {}

  querySelectorAll(selector: string): SvgGroupFixture[] {
    if (selector === "g.node") {
      return this.groups.filter((group) => group.kind === "node");
    }
    if (selector === "g.edge") {
      return this.groups.filter((group) => group.kind === "edge");
    }
    return [];
  }
}

function graphvizSvgFixture() {
  const svg = `
    <svg>
      <g class="node running checkpointed"><title>build</title></g>
      <g class="node completed"><title>deploy</title></g>
      <g class="edge running"><title>approve-&gt;deploy</title></g>
      <g class="edge running"><title>deploy-&gt;notify</title></g>
    </svg>
  `;
  const groups = Array.from(
    svg.matchAll(/<g class="(?<classes>[^"]+)"><title>(?<title>[^<]+)<\/title><\/g>/g)
  ).map((match) => {
    const classes = match.groups?.classes ?? "";
    const title = (match.groups?.title ?? "").replaceAll("&gt;", ">");
    const kind = classes.split(/\s+/).includes("edge") ? "edge" : "node";
    return new SvgGroupFixture(kind, title, classes.split(/\s+/));
  });
  return new SvgRootFixture(groups);
}

function groupClasses(root: SvgRootFixture, titleText: string): string[] {
  const group = root.groups.find((candidate) => candidate.titleText === titleText);
  if (!group) {
    throw new Error(`missing fixture group ${titleText}`);
  }
  return Array.from(group.classNames).sort();
}

const graph: WorkflowGraph = {
  workflow_id: "workflow-1",
  repo_id: "repo-1",
  name: "release",
  dot: "digraph Release { build -> approve; approve -> deploy; deploy -> notify; }",
  nodes: [
    {
      id: "build",
      shape: "box",
      label: "Build",
      effective_handler: "noop",
      attrs: {}
    },
    {
      id: "approve",
      shape: "diamond",
      label: "Approve",
      effective_handler: "approval",
      attrs: {}
    },
    {
      id: "deploy",
      shape: "box",
      label: "Deploy",
      effective_handler: "noop",
      attrs: {}
    },
    {
      id: "notify",
      shape: "box",
      label: "Notify",
      effective_handler: "noop",
      attrs: {}
    }
  ],
  edges: [
    {
      id: "build->approve",
      source: "build",
      target: "approve",
      label: "",
      condition: "",
      weight: 1,
      attrs: {}
    },
    {
      id: "approve->deploy",
      source: "approve",
      target: "deploy",
      label: "",
      condition: "",
      weight: 1,
      attrs: {}
    },
    {
      id: "deploy->notify",
      source: "deploy",
      target: "notify",
      label: "",
      condition: "",
      weight: 1,
      attrs: {}
    }
  ],
  diagnostics: {
    items: []
  }
};

const events: RunEvent[] = [
  {
    sequence: 30,
    event_type: "stage.started",
    payload: { node_id: "deploy" },
    actor_label: "executor",
    created_at: null
  },
  {
    sequence: 10,
    event_type: "stage.completed",
    payload: { name: "build" },
    actor_label: "executor",
    created_at: null
  },
  {
    sequence: 20,
    event_type: "checkpoint.saved",
    payload: { node_id: "build", commit_sha: "a".repeat(40) },
    actor_label: "executor",
    created_at: null
  },
  {
    sequence: 25,
    event_type: "stage.completed",
    payload: { node_id: "approve" },
    actor_label: "executor",
    created_at: null
  },
  {
    sequence: 40,
    event_type: "stage.failed",
    payload: { name: "notify" },
    actor_label: "executor",
    created_at: null
  }
];

const highlightState = buildGraphHighlightState(graph, events);
const waitingHighlightState = buildGraphHighlightState(graph, [
  {
    sequence: 1,
    event_type: "approval.requested",
    payload: { node_id: "approve" },
    actor_label: "executor",
    created_at: null
  }
]);

assertDeepEqual(
  mapEntries(waitingHighlightState.nodeClasses),
  [["approve", ["waiting"]]],
  "marks approval request nodes as waiting"
);

assertDeepEqual(
  mapEntries(highlightState.nodeClasses),
  [
    ["approve", ["completed"]],
    ["build", ["completed", "checkpointed"]],
    ["deploy", ["running"]],
    ["notify", ["failed"]]
  ],
  "normalizes node_id and stage name payloads into node highlight classes"
);

assertDeepEqual(
  mapEntries(highlightState.edgeClasses),
  [["approve->deploy", ["running"]]],
  "marks the edge from the latest completed node to the running node"
);

const buildNode = target("node", "build", ["node", "running", "checkpointed"]);
const deployNode = target("node", "deploy", ["node", "completed"]);
const runningEdge = target("edge", "approve->deploy", ["edge"]);
const staleEdge = target("edge", "deploy->notify", ["edge", "running"]);
const untitledNode = target("node", null, ["node", "failed"]);

applyGraphHighlightClassesToTargets(
  [buildNode, deployNode, runningEdge, staleEdge, untitledNode],
  highlightState
);

assertDeepEqual(
  Array.from(buildNode.classNames).sort(),
  ["checkpointed", "completed", "node"],
  "updates node targets by removing stale highlight classes and adding current classes"
);

assertDeepEqual(
  Array.from(deployNode.classNames).sort(),
  ["node", "running"],
  "applies current running class to node targets"
);

assertDeepEqual(
  Array.from(runningEdge.classNames).sort(),
  ["edge", "running"],
  "applies current running class to edge targets"
);

assertDeepEqual(
  Array.from(staleEdge.classNames).sort(),
  ["edge"],
  "removes stale edge highlights when highlight state changes"
);

assertDeepEqual(
  Array.from(untitledNode.classNames).sort(),
  ["failed", "node"],
  "leaves unidentified graph groups unchanged"
);

const svgRoot = graphvizSvgFixture();

applyGraphHighlightsToRenderedSvg(svgRoot as unknown as ParentNode, highlightState);

assertDeepEqual(
  groupClasses(svgRoot, "build"),
  ["checkpointed", "completed", "node"],
  "updates Graphviz node groups using title text as the node id"
);

assertDeepEqual(
  groupClasses(svgRoot, "deploy"),
  ["node", "running"],
  "replaces stale Graphviz node highlight classes"
);

assertDeepEqual(
  groupClasses(svgRoot, "approve->deploy"),
  ["edge", "running"],
  "applies current highlights to Graphviz edge groups using source->target titles"
);

assertDeepEqual(
  groupClasses(svgRoot, "deploy->notify"),
  ["edge"],
  "removes stale Graphviz edge highlight classes"
);

const highlightOnlyUpdate: GraphViewerUpdateInput = {
  graph,
  events: [
    ...events,
    {
      sequence: 50,
      event_type: "stage.completed",
      payload: { node_id: "deploy" },
      actor_label: "executor",
      created_at: null
    }
  ]
};

assertDeepEqual(
  shouldRenderGraphLayout({ graph, events }, highlightOnlyUpdate),
  false,
  "does not render Graphviz layout again for event-only highlight updates"
);

assertDeepEqual(
  shouldRenderGraphLayout({ graph, events }, { graph: { ...graph, dot: "digraph Changed {}" }, events }),
  true,
  "renders Graphviz layout again when the DOT source changes"
);

const commentBraceDot = `// Compound Conditions and \${braced} Expansion
digraph CommentBrace {
  build -> deploy;
}`;
const themedCommentBraceDot = buildThemedGraphDot(commentBraceDot);
const commentBraceBodyIndex = themedCommentBraceDot.indexOf("digraph CommentBrace {\n  graph [bgcolor");

if (commentBraceBodyIndex === -1) {
  throw new Error("inserts graph theme inside graph body after leading comment braces");
}

if (themedCommentBraceDot.indexOf("graph [bgcolor") < themedCommentBraceDot.indexOf("digraph CommentBrace {")) {
  throw new Error("does not insert graph theme before the graph body");
}

const quotedAttributeBraceDot = `digraph QuotedAttributeBrace {
  graph [label="{quoted body brace}"];
  build -> deploy;
}`;
const themedQuotedAttributeBraceDot = buildThemedGraphDot(quotedAttributeBraceDot);

if (!themedQuotedAttributeBraceDot.includes('graph [bgcolor="transparent"];\n  edge ')) {
  throw new Error("inserts graph theme before quoted graph attributes containing braces");
}

if (!themedQuotedAttributeBraceDot.includes('graph [label="{quoted body brace}"];')) {
  throw new Error("preserves quoted graph attributes containing braces");
}

const htmlStringGraphIdDot = `digraph <G{prod}> {
  build -> deploy;
}`;
const themedHtmlStringGraphIdDot = buildThemedGraphDot(htmlStringGraphIdDot);

if (!themedHtmlStringGraphIdDot.includes("<G{prod}> {\n  graph [bgcolor")) {
  throw new Error("inserts graph theme after HTML-string graph IDs containing braces");
}

if (!themedHtmlStringGraphIdDot.includes("digraph <G{prod}> {")) {
  throw new Error("preserves HTML-string graph IDs containing braces");
}

const graphviz = await Graphviz.load();
const themedGraphSvg = graphviz.layout(graphLayoutKey(graph) ?? "", "svg", "dot");

if (themedGraphSvg.includes('fill="white"')) {
  throw new Error("renders Graphviz SVG without a white canvas polygon");
}

if (!themedGraphSvg.includes('stroke="#8fa0b3"')) {
  throw new Error("renders default graph edges with a muted light stroke");
}

if (!themedGraphSvg.includes('fill="#8fa0b3" stroke="#8fa0b3"')) {
  throw new Error("renders default graph arrowheads with muted light fill and stroke");
}
