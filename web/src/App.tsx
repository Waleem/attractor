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
import { PageHeader, Panel } from "./components/ui";

export default function App() {
  const [path, setPath] = useState(window.location.pathname);

  useEffect(() => {
    const onPopState = () => setPath(window.location.pathname);
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const navigate = useMemo(
    () => (nextPath: string) => {
      window.history.pushState({}, "", nextPath);
      setPath(window.location.pathname);
    },
    []
  );

  return (
    <Layout path={path} navigate={navigate}>
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
  return (
    <>
      <PageHeader title="Not Found" />
      <Panel title="Route">
        <p className="empty-state">No route for {path}</p>
      </Panel>
    </>
  );
}
