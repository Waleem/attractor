import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type PointerEvent
} from "react";
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
  calculateGraphFitTransform,
  graphGroupTitle,
  graphLayoutKey,
  type GraphTransform
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
const GRAPH_ZOOM_STEP = 1.2;
const MIN_GRAPH_ZOOM = 0.2;
const MAX_GRAPH_ZOOM = 4;

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
  const graphSceneRef = useRef<HTMLDivElement | null>(null);
  const dragStateRef = useRef<{
    pointerId: number;
    startX: number;
    startY: number;
    originX: number;
    originY: number;
  } | null>(null);
  const [graphTransform, setGraphTransform] = useState<GraphTransform>({
    scale: 1,
    x: 0,
    y: 0
  });
  const [panning, setPanning] = useState(false);
  const graphDot = graphLayoutKey(graph);

  const fitGraphToCanvas = useCallback(() => {
    const canvas = graphCanvasRef.current;
    const svg = graphSceneRef.current?.querySelector<SVGSVGElement>("svg");
    if (!canvas || !svg) {
      return;
    }
    const canvasRect = canvas.getBoundingClientRect();
    const intrinsicSize = getSvgIntrinsicSize(svg);
    setGraphTransform(
      calculateGraphFitTransform({
        containerWidth: canvasRect.width,
        containerHeight: canvasRect.height,
        contentWidth: intrinsicSize.width,
        contentHeight: intrinsicSize.height
      })
    );
  }, []);

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
    if (!graphSceneRef.current || !svgMarkup) {
      return;
    }
    applyGraphHighlightsToRenderedSvg(graphSceneRef.current, highlightState);
  }, [highlightState, svgMarkup]);

  useLayoutEffect(() => {
    if (!svgMarkup) {
      return;
    }
    fitGraphToCanvas();
  }, [fitGraphToCanvas, svgMarkup]);

  useEffect(() => {
    if (!svgMarkup) {
      return;
    }
    window.addEventListener("resize", fitGraphToCanvas);
    return () => {
      window.removeEventListener("resize", fitGraphToCanvas);
    };
  }, [fitGraphToCanvas, svgMarkup]);

  const zoomGraph = useCallback((scaleMultiplier: number) => {
    const canvas = graphCanvasRef.current;
    if (!canvas) {
      return;
    }
    const canvasRect = canvas.getBoundingClientRect();
    const centerX = canvasRect.width / 2;
    const centerY = canvasRect.height / 2;
    setGraphTransform((current) => {
      const scale = clampGraphZoom(current.scale * scaleMultiplier);
      const contentCenterX = (centerX - current.x) / current.scale;
      const contentCenterY = (centerY - current.y) / current.scale;
      return {
        scale,
        x: centerX - contentCenterX * scale,
        y: centerY - contentCenterY * scale
      };
    });
  }, []);

  const handlePointerDown = useCallback((event: PointerEvent<HTMLDivElement>) => {
    if (!svgMarkup || !event.isPrimary || event.button !== 0) {
      return;
    }
    dragStateRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      originX: graphTransform.x,
      originY: graphTransform.y
    };
    event.currentTarget.setPointerCapture(event.pointerId);
    setPanning(true);
  }, [graphTransform.x, graphTransform.y, svgMarkup]);

  const handlePointerMove = useCallback((event: PointerEvent<HTMLDivElement>) => {
    const dragState = dragStateRef.current;
    if (!dragState || dragState.pointerId !== event.pointerId) {
      return;
    }
    setGraphTransform((current) => ({
      ...current,
      x: dragState.originX + event.clientX - dragState.startX,
      y: dragState.originY + event.clientY - dragState.startY
    }));
  }, []);

  const stopPanning = useCallback((event: PointerEvent<HTMLDivElement>) => {
    const dragState = dragStateRef.current;
    if (!dragState || dragState.pointerId !== event.pointerId) {
      return;
    }
    if (event.currentTarget.hasPointerCapture(dragState.pointerId)) {
      event.currentTarget.releasePointerCapture(dragState.pointerId);
    }
    dragStateRef.current = null;
    setPanning(false);
  }, []);

  return (
    <Panel title="Workflow Graph">
      <div className="graph-viewer">
        <ErrorBanner message={graphState.error ?? renderError} />
        {graphState.loading || rendering ? <Loading label="Rendering graph" /> : null}
        {!graphState.loading && graph && graph.nodes.length === 0 ? (
          <EmptyState>No graph nodes</EmptyState>
        ) : null}
        {svgMarkup ? (
          <>
            <div className="graph-toolbar" role="toolbar" aria-label="Workflow graph controls">
              <button type="button" className="secondary" onClick={fitGraphToCanvas}>
                Fit
              </button>
              <button
                type="button"
                className="secondary"
                aria-label="Zoom out"
                onClick={() => zoomGraph(1 / GRAPH_ZOOM_STEP)}
              >
                -
              </button>
              <button
                type="button"
                className="secondary"
                aria-label="Zoom in"
                onClick={() => zoomGraph(GRAPH_ZOOM_STEP)}
              >
                +
              </button>
            </div>
            <div
              ref={graphCanvasRef}
              className={`graph-canvas${panning ? " is-panning" : ""}`}
              aria-label={`${graph?.name ?? "workflow"} graph`}
              onPointerDown={handlePointerDown}
              onPointerMove={handlePointerMove}
              onPointerUp={stopPanning}
              onPointerCancel={stopPanning}
            >
              <div
                ref={graphSceneRef}
                className="graph-scene"
                style={{
                  transform: `translate(${graphTransform.x}px, ${graphTransform.y}px) scale(${graphTransform.scale})`
                }}
                dangerouslySetInnerHTML={{ __html: svgMarkup }}
              />
            </div>
          </>
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

function clampGraphZoom(scale: number): number {
  return Math.min(MAX_GRAPH_ZOOM, Math.max(MIN_GRAPH_ZOOM, scale));
}

function getSvgIntrinsicSize(svg: SVGSVGElement): { width: number; height: number } {
  const viewBox = svg.viewBox.baseVal;
  if (viewBox.width > 0 && viewBox.height > 0) {
    return { width: viewBox.width, height: viewBox.height };
  }

  return {
    width: readSvgLength(svg.getAttribute("width")),
    height: readSvgLength(svg.getAttribute("height"))
  };
}

function readSvgLength(value: string | null): number {
  if (!value) {
    return 0;
  }
  const parsed = Number.parseFloat(value);
  return Number.isFinite(parsed) ? parsed : 0;
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
  const svg = document.querySelector<SVGSVGElement>("svg");
  if (!svg) {
    throw new Error("Graphviz did not return an SVG");
  }

  sanitizeSvg(document);
  normalizeSvgIntrinsicDimensions(svg);
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

function normalizeSvgIntrinsicDimensions(svg: SVGSVGElement) {
  const viewBox = svg.getAttribute("viewBox")?.trim().split(/\s+/).map(Number);
  if (!viewBox || viewBox.length !== 4) {
    return;
  }
  const [, , width, height] = viewBox;
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
    return;
  }
  svg.setAttribute("width", formatSvgDimension(width));
  svg.setAttribute("height", formatSvgDimension(height));
}

function formatSvgDimension(value: number): string {
  return Number.isInteger(value) ? String(value) : String(Number(value.toFixed(3)));
}
