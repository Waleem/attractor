import { useState, type FormEvent } from "react";
import {
  findWorkflow,
  getProjectConfig,
  launchRun,
  validateWorkflow,
  type ProjectConfigStatus,
  type Workflow
} from "../api";
import { useAsync } from "../components/useAsync";
import { EmptyState, ErrorBanner, Field, KeyValue, Loading, PageHeader, Panel, StatusBadge } from "../components/ui";

export function WorkflowDetailRoute({
  workflowId,
  navigate
}: {
  workflowId: string;
  navigate: (path: string) => void;
}) {
  const workflowState = useAsync(() => findWorkflow(workflowId), [workflowId]);
  const repoId = workflowState.data?.repo.id;
  const configState = useAsync<ProjectConfigStatus | null>(
    () => (repoId ? getProjectConfig(repoId) : Promise.resolve(null)),
    [repoId]
  );
  const [validation, setValidation] = useState<Workflow | null>(null);
  const [actorLabel, setActorLabel] = useState("operator");
  const [inputsJson, setInputsJson] = useState("{}");
  const [submitting, setSubmitting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const repo = workflowState.data?.repo ?? null;
  const workflow = validation ?? workflowState.data?.workflow ?? null;

  async function runValidation() {
    setSubmitting(true);
    setActionError(null);
    try {
      setValidation(await validateWorkflow(workflowId));
    } catch (caught) {
      setActionError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setSubmitting(false);
    }
  }

  async function onLaunch(event: FormEvent) {
    event.preventDefault();
    if (!repo || !workflow) {
      return;
    }
    setSubmitting(true);
    setActionError(null);
    try {
      const inputs = JSON.parse(inputsJson) as Record<string, unknown>;
      const run = await launchRun({
        repo_path: repo.local_path,
        workflow_name: workflow.name,
        actor_label: actorLabel,
        inputs
      });
      navigate(`/runs/${run.id}`);
    } catch (caught) {
      setActionError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
      <PageHeader title={workflow?.name ?? "Workflow"} eyebrow={workflowId} />
      <ErrorBanner message={workflowState.error ?? configState.error ?? actionError} />
      {workflowState.loading ? <Loading /> : null}
      {workflow ? (
        <>
          <Panel
            title="Validation"
            actions={
              <button type="button" onClick={runValidation} disabled={submitting}>
                Validate
              </button>
            }
          >
            <dl className="kv-grid">
              <KeyValue label="Status" value={<StatusBadge status={workflow.status} />} />
              <KeyValue label="DOT path" value={<span className="path-cell">{workflow.dot_path}</span>} />
              <KeyValue label="TOML path" value={<span className="path-cell">{workflow.toml_path ?? "None"}</span>} />
            </dl>
            <Diagnostics workflow={workflow} />
          </Panel>
          <Panel title="Environment Policy">
            {configState.loading ? <Loading /> : null}
            <dl className="kv-grid">
              <KeyValue label="Default" value={configState.data?.config.default_environment ?? "None"} />
              <KeyValue
                label="Allowed modes"
                value={(configState.data?.config.allowed_execution_modes ?? []).join(", ") || "None"}
              />
            </dl>
          </Panel>
          <Panel title="Launch Run">
            <form className="form-stack" onSubmit={onLaunch}>
              <Field label="Actor">
                <input value={actorLabel} onChange={(event) => setActorLabel(event.target.value)} required />
              </Field>
              <Field label="Inputs JSON">
                <textarea rows={6} value={inputsJson} onChange={(event) => setInputsJson(event.target.value)} />
              </Field>
              <button type="submit" disabled={submitting || workflow.status !== "valid"}>
                Launch
              </button>
            </form>
          </Panel>
        </>
      ) : null}
    </>
  );
}

function Diagnostics({ workflow }: { workflow: Workflow }) {
  const items = workflow.diagnostics.items ?? [];
  if (workflow.diagnostics.error) {
    return <div className="error-banner">{workflow.diagnostics.error}</div>;
  }
  if (items.length === 0) {
    return <EmptyState>No diagnostics</EmptyState>;
  }
  return (
    <table>
      <thead>
        <tr>
          <th>Severity</th>
          <th>Rule</th>
          <th>Node</th>
          <th>Message</th>
        </tr>
      </thead>
      <tbody>
        {items.map((item, index) => (
          <tr key={`${item.rule ?? "rule"}-${index}`}>
            <td>{item.severity ?? "info"}</td>
            <td>{item.rule ?? "None"}</td>
            <td>{item.node_id ?? "None"}</td>
            <td>{item.message}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
