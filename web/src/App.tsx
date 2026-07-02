import { useEffect, useMemo, useState } from "react";
import { Layout } from "./components/Layout";
import { DashboardRoute } from "./routes/DashboardRoute";
import { ReposRoute } from "./routes/ReposRoute";
import { RepoDetailRoute } from "./routes/RepoDetailRoute";
import { WorkflowDetailRoute } from "./routes/WorkflowDetailRoute";
import { RunsRoute } from "./routes/RunsRoute";
import { RunDetailRoute } from "./routes/RunDetailRoute";
import { ApprovalsRoute } from "./routes/ApprovalsRoute";
import { SystemRoute } from "./routes/SystemRoute";
import { SettingsRoute } from "./routes/SettingsRoute";
import { PageHeader, Panel } from "./components/ui";
import { getAppBasePath, stripBasePath, toAppHref } from "./appBase";

export default function App() {
  const basePath = useMemo(() => getAppBasePath(), []);
  const [path, setPath] = useState(stripBasePath(window.location.pathname, basePath));

  useEffect(() => {
    const onPopState = () => setPath(stripBasePath(window.location.pathname, basePath));
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [basePath]);

  const navigate = useMemo(
    () => (nextPath: string) => {
      window.history.pushState({}, "", toAppHref(nextPath, basePath));
      setPath(stripBasePath(window.location.pathname, basePath));
    },
    [basePath]
  );

  return (
    <Layout path={path} navigate={navigate} basePath={basePath}>
      <RouteSwitch path={path} navigate={navigate} />
    </Layout>
  );
}

function RouteSwitch({
  path,
  navigate
}: {
  path: string;
  navigate: (path: string) => void;
}) {
  if (path === "/") {
    return <DashboardRoute navigate={navigate} />;
  }
  if (path === "/repos") {
    return <ReposRoute navigate={navigate} />;
  }
  const repoMatch = path.match(/^\/repos\/([^/]+)$/);
  if (repoMatch) {
    return <RepoDetailRoute repoId={decodeURIComponent(repoMatch[1])} navigate={navigate} />;
  }
  const workflowMatch = path.match(/^\/workflows\/([^/]+)$/);
  if (workflowMatch) {
    return <WorkflowDetailRoute workflowId={decodeURIComponent(workflowMatch[1])} navigate={navigate} />;
  }
  if (path === "/runs") {
    return <RunsRoute navigate={navigate} />;
  }
  const runMatch = path.match(/^\/runs\/([^/]+)$/);
  if (runMatch) {
    return <RunDetailRoute runId={decodeURIComponent(runMatch[1])} />;
  }
  if (path === "/approvals") {
    return <ApprovalsRoute navigate={navigate} />;
  }
  if (path === "/system") {
    return <SystemRoute />;
  }
  if (path === "/settings") {
    return <SettingsRoute />;
  }
  return (
    <>
      <PageHeader title="Not Found" />
      <Panel title="Route">
        <p className="empty-state">No route for {path}</p>
      </Panel>
    </>
  );
}
