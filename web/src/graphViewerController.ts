import type { RunEvent, WorkflowGraph } from "./api.js";
import {
  applyGraphHighlightClassesToTargets,
  type GraphHighlightClassTarget,
  type GraphHighlightState
} from "./graphHighlight.js";

export interface GraphViewerUpdateInput {
  graph: WorkflowGraph | null | undefined;
  events: RunEvent[];
}

export function graphLayoutKey(graph: WorkflowGraph | null | undefined): string | null {
  return graph?.dot ?? null;
}

export function shouldRenderGraphLayout(
  previous: GraphViewerUpdateInput,
  next: GraphViewerUpdateInput
): boolean {
  return graphLayoutKey(previous.graph) !== graphLayoutKey(next.graph);
}

export function applyGraphHighlightsToRenderedSvg(
  root: ParentNode,
  highlightState: GraphHighlightState
) {
  const targets: GraphHighlightClassTarget[] = [];

  root.querySelectorAll<SVGGElement>("g.node").forEach((group) => {
    targets.push({
      kind: "node",
      id: group.getAttribute("data-node-id") ?? graphGroupTitle(group),
      addClass(className: string) {
        group.classList.add(className);
      },
      removeClass(className: string) {
        group.classList.remove(className);
      }
    });
  });

  root.querySelectorAll<SVGGElement>("g.edge").forEach((group) => {
    targets.push({
      kind: "edge",
      id: group.getAttribute("data-edge-id") ?? graphGroupTitle(group),
      addClass(className: string) {
        group.classList.add(className);
      },
      removeClass(className: string) {
        group.classList.remove(className);
      }
    });
  });

  applyGraphHighlightClassesToTargets(targets, highlightState);
}

export function graphGroupTitle(group: SVGGElement): string | null {
  const title = group.querySelector("title")?.textContent?.trim();
  return title && title.length > 0 ? title : null;
}
