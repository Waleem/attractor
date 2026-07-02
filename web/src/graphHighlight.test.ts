import { buildGraphHighlightState } from "./graphHighlight.js";
import type { RunEvent, WorkflowGraph } from "./api";

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

const graph: WorkflowGraph = {
  workflow_id: "workflow-1",
  repo_id: "repo-1",
  name: "release",
  dot: "digraph Release {}",
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

assertDeepEqual(
  mapEntries(highlightState.nodeClasses),
  [
    ["approve", ["complete"]],
    ["build", ["complete", "checkpointed"]],
    ["deploy", ["active"]],
    ["notify", ["failed"]]
  ],
  "normalizes node_id and stage name payloads into node highlight classes"
);

assertDeepEqual(
  mapEntries(highlightState.edgeClasses),
  [["approve->deploy", ["active"]]],
  "marks the edge from the latest completed node to the active node"
);
