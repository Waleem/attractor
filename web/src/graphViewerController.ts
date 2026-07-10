import type { RunEvent, WorkflowGraph } from "./api.js";
import {
  applyGraphHighlightClassesToTargets,
  type GraphHighlightClassTarget,
  type GraphHighlightState
} from "./graphHighlight.js";

const GRAPH_EDGE_COLOR = "#8fa0b3";
const GRAPH_LABEL_COLOR = "#eef2f7";
const GRAPH_NODE_BORDER_COLOR = "#7f8fa3";
const GRAPH_NODE_FONT_SIZE = "10.5";
const GRAPH_NODE_WIDTH = "0.56";
const GRAPH_NODE_HEIGHT = "0.38";
const DEFAULT_GRAPH_FIT_PADDING = 24;
const DEFAULT_GRAPH_MAX_FIT_SCALE = 1.5;

export interface GraphFitInput {
  containerWidth: number;
  containerHeight: number;
  contentWidth: number;
  contentHeight: number;
  padding?: number;
  maxScale?: number;
}

export interface GraphTransform {
  scale: number;
  x: number;
  y: number;
}

export interface GraphViewerUpdateInput {
  graph: WorkflowGraph | null | undefined;
  events: RunEvent[];
}

export function graphLayoutKey(graph: WorkflowGraph | null | undefined): string | null {
  return graph?.dot ? buildThemedGraphDot(graph.dot) : null;
}

export function buildThemedGraphDot(dot: string): string {
  const openingBraceIndex = findGraphBodyOpeningBrace(dot);
  if (openingBraceIndex === -1) {
    return dot;
  }

  const themeStatements = [
    '  graph [bgcolor="transparent", rankdir="LR"];',
    `  edge [color="${GRAPH_EDGE_COLOR}", fontcolor="${GRAPH_EDGE_COLOR}"];`,
    `  node [color="${GRAPH_NODE_BORDER_COLOR}", fontcolor="${GRAPH_LABEL_COLOR}", fontsize="${GRAPH_NODE_FONT_SIZE}", width="${GRAPH_NODE_WIDTH}", height="${GRAPH_NODE_HEIGHT}"];`
  ].join("\n");

  return `${dot.slice(0, openingBraceIndex + 1)}\n${themeStatements}\n${dot.slice(openingBraceIndex + 1)}`;
}

function findGraphBodyOpeningBrace(dot: string): number {
  for (let index = 0; index < dot.length;) {
    index = skipIgnoredDotRange(dot, index);
    if (index >= dot.length) {
      return -1;
    }

    const token = readDotIdentifier(dot, index);
    if (token) {
      if (token.value === "graph" || token.value === "digraph") {
        return findOpeningBraceAfterGraphKeyword(dot, token.end);
      }
      index = token.end;
      continue;
    }

    index += 1;
  }

  return -1;
}

function findOpeningBraceAfterGraphKeyword(dot: string, startIndex: number): number {
  for (let index = startIndex; index < dot.length;) {
    index = skipIgnoredDotRange(dot, index);
    if (index >= dot.length) {
      return -1;
    }
    if (dot[index] === "{") {
      return index;
    }
    index += 1;
  }

  return -1;
}

function skipIgnoredDotRange(dot: string, startIndex: number): number {
  const current = dot[startIndex];
  const next = dot[startIndex + 1];
  if (current === "/" && next === "/") {
    return skipUntilLineEnd(dot, startIndex + 2);
  }
  if (current === "/" && next === "*") {
    return skipBlockComment(dot, startIndex + 2);
  }
  if (current === "#") {
    return skipUntilLineEnd(dot, startIndex + 1);
  }
  if (current === "\"") {
    return skipQuotedString(dot, startIndex + 1);
  }
  if (current === "<") {
    return skipHtmlString(dot, startIndex + 1);
  }
  return startIndex;
}

function skipUntilLineEnd(dot: string, startIndex: number): number {
  const lineEndIndex = dot.indexOf("\n", startIndex);
  return lineEndIndex === -1 ? dot.length : lineEndIndex + 1;
}

function skipBlockComment(dot: string, startIndex: number): number {
  const commentEndIndex = dot.indexOf("*/", startIndex);
  return commentEndIndex === -1 ? dot.length : commentEndIndex + 2;
}

function skipQuotedString(dot: string, startIndex: number): number {
  for (let index = startIndex; index < dot.length; index += 1) {
    if (dot[index] === "\\") {
      index += 1;
      continue;
    }
    if (dot[index] === "\"") {
      return index + 1;
    }
  }

  return dot.length;
}

function skipHtmlString(dot: string, startIndex: number): number {
  let depth = 1;
  for (let index = startIndex; index < dot.length; index += 1) {
    if (dot[index] === "\"") {
      index = skipQuotedString(dot, index + 1) - 1;
      continue;
    }
    if (dot[index] === "<") {
      depth += 1;
      continue;
    }
    if (dot[index] === ">") {
      depth -= 1;
      if (depth === 0) {
        return index + 1;
      }
    }
  }

  return dot.length;
}

function readDotIdentifier(dot: string, startIndex: number): { value: string; end: number } | null {
  const firstCharacter = dot[startIndex];
  if (!/[A-Za-z_\u0080-\uFFFF]/.test(firstCharacter)) {
    return null;
  }

  let end = startIndex + 1;
  while (end < dot.length && /[A-Za-z0-9_\u0080-\uFFFF]/.test(dot[end])) {
    end += 1;
  }

  return { value: dot.slice(startIndex, end).toLowerCase(), end };
}

export function shouldRenderGraphLayout(
  previous: GraphViewerUpdateInput,
  next: GraphViewerUpdateInput
): boolean {
  return graphLayoutKey(previous.graph) !== graphLayoutKey(next.graph);
}

export function calculateGraphFitTransform(input: GraphFitInput): GraphTransform {
  const padding = input.padding ?? DEFAULT_GRAPH_FIT_PADDING;
  const maxScale = input.maxScale ?? DEFAULT_GRAPH_MAX_FIT_SCALE;
  const availableWidth = Math.max(1, input.containerWidth - padding * 2);
  const availableHeight = Math.max(1, input.containerHeight - padding * 2);

  if (
    input.containerWidth <= 0 ||
    input.containerHeight <= 0 ||
    input.contentWidth <= 0 ||
    input.contentHeight <= 0
  ) {
    return { scale: 1, x: padding, y: padding };
  }

  const scale = Math.min(
    availableWidth / input.contentWidth,
    availableHeight / input.contentHeight,
    maxScale
  );
  const x = Math.max(padding, (input.containerWidth - input.contentWidth * scale) / 2);
  const y = Math.max(padding, (input.containerHeight - input.contentHeight * scale) / 2);

  return {
    scale: roundGraphTransformValue(scale),
    x: roundGraphTransformValue(x),
    y: roundGraphTransformValue(y)
  };
}

function roundGraphTransformValue(value: number): number {
  return Math.round(value * 1_000_000) / 1_000_000;
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
