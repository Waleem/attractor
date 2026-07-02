import {
  apiPath,
  inferBasePathFromPathname,
  normalizeBasePath,
  stripBasePath,
  toAppHref
} from "./appBase.js";

function assertEqual(actual: unknown, expected: unknown, message: string) {
  if (actual !== expected) {
    throw new Error(`${message}\nexpected: ${String(expected)}\nactual:   ${String(actual)}`);
  }
}

assertEqual(normalizeBasePath(""), "", "empty base normalizes to root");
assertEqual(normalizeBasePath("/"), "", "slash base normalizes to root");
assertEqual(normalizeBasePath("./"), "", "relative Vite base normalizes to root");
assertEqual(normalizeBasePath("/console/"), "/console", "trailing slash is removed");
assertEqual(
  normalizeBasePath("https://example.test/console/"),
  "/console",
  "absolute base URLs normalize to their path"
);

assertEqual(
  inferBasePathFromPathname("/console/runs/123"),
  "/console",
  "run routes infer prefixed app base"
);
assertEqual(
  inferBasePathFromPathname("/runs/123"),
  "",
  "root run routes infer root app base"
);
assertEqual(
  inferBasePathFromPathname("/unknown"),
  "",
  "unknown root routes stay unprefixed"
);

assertEqual(stripBasePath("/console/runs/123", "/console"), "/runs/123", "base is stripped");
assertEqual(stripBasePath("/console", "/console"), "/", "base root strips to app root");
assertEqual(stripBasePath("/runs/123", ""), "/runs/123", "root base leaves path unchanged");
assertEqual(stripBasePath("/console-extra/runs/123", "/console"), "/console-extra/runs/123", "partial base segments are not stripped");

assertEqual(toAppHref("/", "/console"), "/console", "root link preserves prefix");
assertEqual(toAppHref("/runs/123", "/console"), "/console/runs/123", "route link preserves prefix");
assertEqual(toAppHref("/runs/123?tab=events", "/console"), "/console/runs/123?tab=events", "query strings are preserved");
assertEqual(toAppHref("/runs/123", ""), "/runs/123", "root deployment keeps absolute route links");

assertEqual(apiPath("/api/runs", "", "/console"), "/console/api/runs", "API calls preserve prefix");
assertEqual(apiPath("/api/runs", "", ""), "/api/runs", "root API calls stay at root");
assertEqual(
  apiPath("/api/runs", "http://127.0.0.1:8000/", "/console"),
  "http://127.0.0.1:8000/api/runs",
  "explicit API base overrides app prefix"
);
