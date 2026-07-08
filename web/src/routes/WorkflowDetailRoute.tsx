import { useState, type FormEvent } from "react";
import {
  findWorkflow,
  getProjectConfig,
  launchRun,
  validateWorkflow,
  type ProjectConfigStatus,
  type Workflow
} from "../api";
import { GraphViewer } from "../components/GraphViewer";
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
  const [requestedEnvironment, setRequestedEnvironment] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [launchDiagnostic, setLaunchDiagnostic] = useState<string | null>(null);

  const repo = workflowState.data?.repo ?? null;
  const workflow = validation ?? workflowState.data?.workflow ?? null;
  const environmentOptions = environmentNames(configState.data?.config);

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
    setLaunchDiagnostic(null);
    try {
      const parsedInputs = JSON.parse(inputsJson) as unknown;
      if (!isStringRecord(parsedInputs)) {
        setLaunchDiagnostic("Inputs JSON must be an object with string values.");
        return;
      }
      const run = await launchRun({
        repo_path: repo.local_path,
        workflow_name: workflow.name,
        actor_label: actorLabel,
        inputs: parsedInputs,
        requested_environment: requestedEnvironment
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
          <GraphViewer workflowId={workflowId} events={[]} />
          <Panel title="Launch Run">
            <form className="form-stack" onSubmit={onLaunch}>
              <Field label="Actor">
                <input value={actorLabel} onChange={(event) => setActorLabel(event.target.value)} required />
              </Field>
              <Field label="Environment">
                <select
                  value={requestedEnvironment}
                  onChange={(event) => setRequestedEnvironment(event.target.value)}
                >
                  <option value="">Project default</option>
                  {environmentOptions.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Inputs JSON">
                <textarea rows={6} value={inputsJson} onChange={(event) => setInputsJson(event.target.value)} />
              </Field>
              {launchDiagnostic ? <div className="error-banner">{launchDiagnostic}</div> : null}
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

function environmentNames(config: ProjectConfigStatus["config"] | undefined): string[] {
  if (!config) {
    return [];
  }
  const allowedModes = new Set(config.allowed_execution_modes ?? []);
  const names = new Set<string>();

  function addIfAllowed(name: string, mode: string | undefined = name) {
    if (!name || !allowedModes.has(mode)) {
      return;
    }
    names.add(name);
  }

  const defaultEnvironment = config.default_environment;
  if (defaultEnvironment) {
    addIfAllowed(defaultEnvironment, config.environments?.[defaultEnvironment]?.mode);
  }
  for (const mode of config.allowed_execution_modes ?? []) {
    names.add(mode);
  }
  for (const [name, environment] of Object.entries(config.environments ?? {})) {
    addIfAllowed(name, environment.mode);
  }
  return [...names];
}

function isStringRecord(value: unknown): value is Record<string, string> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }
  return Object.entries(value).every(
    ([key, item]) => typeof key === "string" && typeof item === "string"
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
