import type { RunEvent, WorkflowGraph, WorkflowGraphEdge } from "./api";

export type GraphNodeClass = "active" | "complete" | "failed" | "checkpointed";
export type GraphEdgeClass = "active";

export const GRAPH_NODE_HIGHLIGHT_CLASSES: readonly GraphNodeClass[] = [
  "active",
  "complete",
  "failed",
  "checkpointed"
];
export const GRAPH_EDGE_HIGHLIGHT_CLASSES: readonly GraphEdgeClass[] = ["active"];

export interface GraphHighlightState {
  nodeClasses: Map<string, GraphNodeClass[]>;
  edgeClasses: Map<string, GraphEdgeClass[]>;
}

export interface GraphHighlightClassTarget {
  kind: "node" | "edge";
  id: string | null;
  addClass: (className: string) => void;
  removeClass: (className: string) => void;
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
      edgeClasses.set(graphEdgeId(activeEdge), ["active"]);
    }
  }

  return { nodeClasses, edgeClasses };
}

export function graphEdgeId(edge: WorkflowGraphEdge): string {
  return edge.id || `${edge.source}->${edge.target}`;
}

export function applyGraphHighlightClassesToTargets(
  targets: GraphHighlightClassTarget[],
  highlightState: GraphHighlightState
) {
  for (const target of targets) {
    if (!target.id) {
      continue;
    }

    const managedClasses =
      target.kind === "node" ? GRAPH_NODE_HIGHLIGHT_CLASSES : GRAPH_EDGE_HIGHLIGHT_CLASSES;
    for (const className of managedClasses) {
      target.removeClass(className);
    }

    const classes =
      target.kind === "node"
        ? highlightState.nodeClasses.get(target.id)
        : highlightState.edgeClasses.get(target.id);
    if (classes) {
      for (const className of classes) {
        target.addClass(className);
      }
    }
  }
}

function eventNodeId(event: RunEvent): string | null {
  const value = event.payload.node_id ?? event.payload.name;
  return typeof value === "string" && value.length > 0 ? value : null;
}
