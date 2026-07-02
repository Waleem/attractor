import { useEffect, useMemo, useState, type CSSProperties } from "react";
import {
  getWorkflowGraph,
  type RunEvent,
  type WorkflowGraph,
  type WorkflowGraphEdge
} from "../api";
import { useAsync } from "./useAsync";
import { EmptyState, ErrorBanner, Loading, Panel } from "./ui";

type GraphNodeClass = "active" | "complete" | "failed" | "checkpointed";
type GraphEdgeClass = "active";
type GraphvizRenderer = {
  layout: (dot: string, format?: string, engine?: string) => string;
};
type GraphvizModule = {
  Graphviz: {
    load: () => Promise<GraphvizRenderer>;
  };
};

export interface GraphHighlightState {
  nodeClasses: Map<string, GraphNodeClass[]>;
  edgeClasses: Map<string, GraphEdgeClass[]>;
}

const GRAPH_SVG_STYLE = `
svg {
  max-width: 100%;
  height: auto;
}
.node polygon,
.node ellipse,
.node path {
  transition: fill 120ms ease, stroke 120ms ease, stroke-width 120ms ease;
}
.edge path,
.edge polygon {
  transition: fill 120ms ease, stroke 120ms ease, stroke-width 120ms ease;
}
.node.complete polygon,
.node.complete ellipse,
.node.complete path {
  fill: #dcefe5;
  stroke: #2f7d52;
}
.node.active polygon,
.node.active ellipse,
.node.active path {
  fill: #d8e9fb;
  stroke: #245a9f;
  stroke-width: 2;
}
.node.checkpointed polygon,
.node.checkpointed ellipse,
.node.checkpointed path {
  stroke-dasharray: 5 3;
}
.node.failed polygon,
.node.failed ellipse,
.node.failed path {
  fill: #f7dada;
  stroke: #b44343;
  stroke-width: 2;
}
.edge.active path {
  stroke: #245a9f;
  stroke-width: 2.5;
}
.edge.active polygon {
  fill: #245a9f;
  stroke: #245a9f;
}
`;

const shellStyle: CSSProperties = {
  display: "grid",
  gap: "0.8rem"
};

const graphCanvasStyle: CSSProperties = {
  overflowX: "auto",
  border: "1px solid #d8dee6",
  borderRadius: 6,
  background: "#ffffff",
  padding: "0.75rem"
};

const legendStyle: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: "0.55rem",
  color: "#526173",
  fontSize: "0.82rem"
};

const swatchBaseStyle: CSSProperties = {
  width: 12,
  height: 12,
  borderRadius: 2,
  display: "inline-block",
  marginRight: 5,
  verticalAlign: -1
};

export function GraphViewer({ workflowId, events }: { workflowId: string; events: RunEvent[] }) {
  const graphState = useAsync(() => getWorkflowGraph(workflowId), [workflowId]);
  const graph = graphState.data;
  const highlightState = useMemo(
    () => (graph ? buildGraphHighlightState(graph, events) : emptyHighlightState()),
    [graph, events]
  );
  const [svgMarkup, setSvgMarkup] = useState("");
  const [renderError, setRenderError] = useState<string | null>(null);
  const [rendering, setRendering] = useState(false);

  useEffect(() => {
    let active = true;
    if (!graph) {
      setSvgMarkup("");
      return () => {
        active = false;
      };
    }

    setRendering(true);
    setRenderError(null);
    renderDotToSvg(graph.dot)
      .then((svg) => applyGraphHighlights(svg, graph, highlightState))
      .then((svg) => {
        if (active) {
          setSvgMarkup(svg);
        }
      })
      .catch((caught: unknown) => {
        if (active) {
          setRenderError(caught instanceof Error ? caught.message : String(caught));
          setSvgMarkup("");
        }
      })
      .finally(() => {
        if (active) {
          setRendering(false);
        }
      });

    return () => {
      active = false;
    };
  }, [graph, highlightState]);

  return (
    <Panel title="Workflow Graph">
      <div style={shellStyle}>
        <ErrorBanner message={graphState.error ?? renderError} />
        {graphState.loading || rendering ? <Loading label="Rendering graph" /> : null}
        {!graphState.loading && graph && graph.nodes.length === 0 ? (
          <EmptyState>No graph nodes</EmptyState>
        ) : null}
        {svgMarkup ? (
          <div
            style={graphCanvasStyle}
            aria-label={`${graph?.name ?? "workflow"} graph`}
            dangerouslySetInnerHTML={{ __html: svgMarkup }}
          />
        ) : null}
        {graph ? <GraphLegend /> : null}
      </div>
    </Panel>
  );
}

export function buildGraphHighlightState(
  graph: WorkflowGraph,
  events: RunEvent[]
): GraphHighlightState {
  const nodeClasses = new Map<string, GraphNodeClass[]>();
  const edgeClasses = new Map<string, GraphEdgeClass[]>();
  const completed = new Set<string>();
  const failed = new Set<string>();
  const checkpointed = new Set<string>();
  let activeNode: string | null = null;
  let latestCompletedNode: string | null = null;

  for (const event of [...events].sort((a, b) => a.sequence - b.sequence)) {
    const nodeId = eventNodeId(event);
    if (!nodeId) {
      continue;
    }
    if (event.event_type === "stage.started") {
      activeNode = nodeId;
    } else if (event.event_type === "stage.completed") {
      completed.add(nodeId);
      latestCompletedNode = nodeId;
      if (activeNode === nodeId) {
        activeNode = null;
      }
    } else if (event.event_type === "stage.failed") {
      failed.add(nodeId);
      if (activeNode === nodeId) {
        activeNode = null;
      }
    } else if (event.event_type === "checkpoint.saved") {
      checkpointed.add(nodeId);
    }
  }

  for (const node of graph.nodes) {
    const classes: GraphNodeClass[] = [];
    if (completed.has(node.id)) {
      classes.push("complete");
    }
    if (activeNode === node.id) {
      classes.push("active");
    }
    if (checkpointed.has(node.id)) {
      classes.push("checkpointed");
    }
    if (failed.has(node.id)) {
      classes.push("failed");
    }
    if (classes.length > 0) {
      nodeClasses.set(node.id, classes);
    }
  }

  if (latestCompletedNode && activeNode) {
    const activeEdge = graph.edges.find(
      (edge) => edge.source === latestCompletedNode && edge.target === activeNode
    );
    if (activeEdge) {
      edgeClasses.set(edgeId(activeEdge), ["active"]);
    }
  }

  return { nodeClasses, edgeClasses };
}

function GraphLegend() {
  return (
    <div style={legendStyle}>
      <span>
        <span style={{ ...swatchBaseStyle, background: "#d8e9fb", border: "1px solid #245a9f" }} />
        active
      </span>
      <span>
        <span style={{ ...swatchBaseStyle, background: "#dcefe5", border: "1px solid #2f7d52" }} />
        complete
      </span>
      <span>
        <span style={{ ...swatchBaseStyle, background: "#f7dada", border: "1px solid #b44343" }} />
        failed
      </span>
      <span>
        <span
          style={{
            ...swatchBaseStyle,
            background: "#ffffff",
            border: "1px dashed #526173"
          }}
        />
        checkpointed
      </span>
    </div>
  );
}

function emptyHighlightState(): GraphHighlightState {
  return { nodeClasses: new Map(), edgeClasses: new Map() };
}

async function renderDotToSvg(dot: string): Promise<string> {
  const graphvizModule = (await import("@hpcc-js/wasm/graphviz")) as unknown as GraphvizModule;
  const graphviz = await graphvizModule.Graphviz.load();
  return graphviz.layout(dot, "svg", "dot");
}

function eventNodeId(event: RunEvent): string | null {
  const value = event.payload.node_id ?? event.payload.name;
  return typeof value === "string" && value.length > 0 ? value : null;
}

function applyGraphHighlights(
  svgText: string,
  graph: WorkflowGraph,
  highlightState: GraphHighlightState
): string {
  const document = new DOMParser().parseFromString(svgText, "image/svg+xml");
  const parserError = document.querySelector("parsererror");
  if (parserError) {
    throw new Error(parserError.textContent ?? "Unable to parse rendered SVG");
  }
  const svg = document.querySelector("svg");
  if (!svg) {
    throw new Error("Graphviz did not return an SVG");
  }

  sanitizeSvg(document);
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", `${graph.name} workflow graph`);

  const style = document.createElementNS("http://www.w3.org/2000/svg", "style");
  style.textContent = GRAPH_SVG_STYLE;
  svg.insertBefore(style, svg.firstChild);

  document.querySelectorAll<SVGGElement>("g.node").forEach((group) => {
    const nodeId = groupTitle(group);
    if (!nodeId) {
      return;
    }
    group.setAttribute("data-node-id", nodeId);
    const classes = highlightState.nodeClasses.get(nodeId);
    if (classes) {
      group.classList.add(...classes);
    }
  });

  const edgeTitleById = new Map<string, string>();
  for (const edge of graph.edges) {
    edgeTitleById.set(edgeId(edge), edgeId(edge));
  }

  document.querySelectorAll<SVGGElement>("g.edge").forEach((group) => {
    const title = groupTitle(group);
    if (!title) {
      return;
    }
    const edgeIdFromTitle = edgeTitleById.get(title);
    if (!edgeIdFromTitle) {
      return;
    }
    group.setAttribute("data-edge-id", edgeIdFromTitle);
    const classes = highlightState.edgeClasses.get(edgeIdFromTitle);
    if (classes) {
      group.classList.add(...classes);
    }
  });

  return new XMLSerializer().serializeToString(svg);
}

function sanitizeSvg(document: Document) {
  document.querySelectorAll("script").forEach((element) => element.remove());
  document.querySelectorAll<Element>("*").forEach((element) => {
    for (const attribute of Array.from(element.attributes)) {
      if (attribute.name.toLowerCase().startsWith("on")) {
        element.removeAttribute(attribute.name);
      }
    }
  });
}

function groupTitle(group: SVGGElement): string | null {
  const title = group.querySelector("title")?.textContent?.trim();
  return title && title.length > 0 ? title : null;
}

function edgeId(edge: WorkflowGraphEdge): string {
  return edge.id || `${edge.source}->${edge.target}`;
}
