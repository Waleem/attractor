import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
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
import {
  applyGraphHighlightsToRenderedSvg,
  graphGroupTitle,
  graphLayoutKey
} from "../graphViewerController";
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
let graphvizLoadPromise: Promise<GraphvizRenderer> | null = null;

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
  const graphCanvasRef = useRef<HTMLDivElement | null>(null);
  const graphDot = graphLayoutKey(graph);

  useEffect(() => {
    let active = true;
    if (!graph || graphDot === null) {
      setSvgMarkup("");
      setRendering(false);
      return () => {
        active = false;
      };
    }

    setRendering(true);
    setRenderError(null);
    renderDotToSvg(graphDot)
      .then((svg) => prepareGraphSvg(svg, graph))
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
  }, [graphDot]);

  useLayoutEffect(() => {
    if (!graphCanvasRef.current || !svgMarkup) {
      return;
    }
    applyGraphHighlightsToRenderedSvg(graphCanvasRef.current, highlightState);
  }, [highlightState, svgMarkup]);

  return (
    <Panel title="Workflow Graph">
      <div className="graph-viewer">
        <ErrorBanner message={graphState.error ?? renderError} />
        {graphState.loading || rendering ? <Loading label="Rendering graph" /> : null}
        {!graphState.loading && graph && graph.nodes.length === 0 ? (
          <EmptyState>No graph nodes</EmptyState>
        ) : null}
        {svgMarkup ? (
          <div
            ref={graphCanvasRef}
            className="graph-canvas"
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
    <div className="graph-legend">
      <span className="graph-legend-item">
        <span className="graph-swatch graph-swatch-running" aria-hidden="true" />
        running
      </span>
      <span className="graph-legend-item">
        <span className="graph-swatch graph-swatch-waiting" aria-hidden="true" />
        waiting
      </span>
      <span className="graph-legend-item">
        <span className="graph-swatch graph-swatch-completed" aria-hidden="true" />
        completed
      </span>
      <span className="graph-legend-item">
        <span className="graph-swatch graph-swatch-failed" aria-hidden="true" />
        failed
      </span>
      <span className="graph-legend-item">
        <span className="graph-swatch graph-swatch-checkpointed" aria-hidden="true" />
        checkpointed
      </span>
    </div>
  );
}

function emptyHighlightState(): GraphHighlightState {
  return { nodeClasses: new Map(), edgeClasses: new Map() };
}

async function renderDotToSvg(dot: string): Promise<string> {
  const graphviz = await loadGraphvizRenderer();
  return graphviz.layout(dot, "svg", "dot");
}

async function loadGraphvizRenderer(): Promise<GraphvizRenderer> {
  if (!graphvizLoadPromise) {
    graphvizLoadPromise = import("@hpcc-js/wasm/graphviz")
      .then((graphvizModule) =>
        (graphvizModule as unknown as GraphvizModule).Graphviz.load()
      )
      .catch((caught: unknown) => {
        graphvizLoadPromise = null;
        throw caught;
      });
  }
  return graphvizLoadPromise;
}

function prepareGraphSvg(
  svgText: string,
  graph: WorkflowGraph
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

  document.querySelectorAll<SVGGElement>("g.node").forEach((group) => {
    const nodeId = graphGroupTitle(group);
    if (!nodeId) {
      return;
    }
    group.setAttribute("data-node-id", nodeId);
  });

  const edgeTitleById = new Map<string, string>();
  for (const edge of graph.edges) {
    edgeTitleById.set(graphEdgeId(edge), graphEdgeId(edge));
  }

  document.querySelectorAll<SVGGElement>("g.edge").forEach((group) => {
    const title = graphGroupTitle(group);
    if (!title) {
      return;
    }
    const edgeIdFromTitle = edgeTitleById.get(title);
    if (!edgeIdFromTitle) {
      return;
    }
    group.setAttribute("data-edge-id", edgeIdFromTitle);
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
