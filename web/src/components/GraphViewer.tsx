import { useEffect, useMemo, useState, type CSSProperties } from "react";
import {
  getWorkflowGraph,
  type RunEvent,
  type WorkflowGraph
} from "../api";
import {
  buildGraphHighlightState,
  graphEdgeId,
  type GraphHighlightState
} from "../graphHighlight";
import { useAsync } from "./useAsync";
import { EmptyState, ErrorBanner, Loading, Panel } from "./ui";

type GraphvizRenderer = {
  layout: (dot: string, format?: string, engine?: string) => string;
};
type GraphvizModule = {
  Graphviz: {
    load: () => Promise<GraphvizRenderer>;
  };
};

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
    edgeTitleById.set(graphEdgeId(edge), graphEdgeId(edge));
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
