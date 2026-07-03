import type { RunEvent, WorkflowGraph, WorkflowGraphEdge } from "./api";

export type GraphNodeClass = "running" | "waiting" | "completed" | "failed" | "checkpointed";
export type GraphEdgeClass = "running";

export const GRAPH_NODE_HIGHLIGHT_CLASSES: readonly GraphNodeClass[] = [
  "running",
  "waiting",
  "completed",
  "failed",
  "checkpointed"
];
export const GRAPH_EDGE_HIGHLIGHT_CLASSES: readonly GraphEdgeClass[] = ["running"];

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
  const waiting = new Set<string>();
  const checkpointed = new Set<string>();
  let runningNode: string | null = null;
  let latestCompletedNode: string | null = null;

  for (const event of [...events].sort((a, b) => a.sequence - b.sequence)) {
    const nodeId = eventNodeId(event);
    if (!nodeId) {
      continue;
    }
    if (event.event_type === "stage.started") {
      runningNode = nodeId;
      waiting.delete(nodeId);
    } else if (event.event_type === "stage.completed") {
      completed.add(nodeId);
      latestCompletedNode = nodeId;
      waiting.delete(nodeId);
      if (runningNode === nodeId) {
        runningNode = null;
      }
    } else if (event.event_type === "stage.failed") {
      failed.add(nodeId);
      waiting.delete(nodeId);
      if (runningNode === nodeId) {
        runningNode = null;
      }
    } else if (event.event_type === "checkpoint.saved") {
      checkpointed.add(nodeId);
    } else if (event.event_type === "approval.requested") {
      waiting.add(nodeId);
      if (runningNode === nodeId) {
        runningNode = null;
      }
    } else if (event.event_type === "approval.decided") {
      waiting.delete(nodeId);
    }
  }

  for (const node of graph.nodes) {
    const classes: GraphNodeClass[] = [];
    if (completed.has(node.id)) {
      classes.push("completed");
    }
    if (runningNode === node.id) {
      classes.push("running");
    }
    if (waiting.has(node.id)) {
      classes.push("waiting");
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

  if (latestCompletedNode && runningNode) {
    const activeEdge = graph.edges.find(
      (edge) => edge.source === latestCompletedNode && edge.target === runningNode
    );
    if (activeEdge) {
      edgeClasses.set(graphEdgeId(activeEdge), ["running"]);
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
