import { apiPath } from "./appBase";

export type RunStatus =
  | "queued"
  | "preparing"
  | "running"
  | "waiting_for_approval"
  | "completed"
  | "failed"
  | "cancelled"
  | "writeback_pending"
  | "writeback_applied"
  | "writeback_failed"
  | string;

export interface Repo {
  id: string;
  name: string;
  local_path: string;
  default_branch: string;
  current_commit: string;
  dirty_state: string;
  project_config_status: string;
  created_at: string | null;
  updated_at: string | null;
  last_indexed_at: string | null;
  workflow_count?: number;
  project_config?: ProjectConfig;
}

export interface RepoRefreshResult {
  repo: Repo;
  workflow_count: number;
  removed_workflow_count: number;
  changed: boolean;
  active_workflow_ids?: string[];
}

export interface WorkflowDiagnostic {
  rule?: string;
  severity?: string;
  message: string;
  node_id?: string | null;
  edge_index?: number | null;
  edge_id?: string | null;
}

export interface Workflow {
  id: string;
  repo_id: string;
  name: string;
  dot_path: string;
  toml_path: string | null;
  status: string;
  diagnostics: {
    error?: unknown;
    items?: WorkflowDiagnostic[];
  };
  indexed_at?: string | null;
}

export interface WorkflowGraphNode {
  id: string;
  shape: string;
  label: string;
  effective_handler: string;
  attrs: Record<string, unknown>;
}

export interface WorkflowGraphEdge {
  id: string;
  source: string;
  target: string;
  label: string;
  condition: string;
  weight: number;
  attrs: Record<string, unknown>;
}

export interface WorkflowGraph {
  workflow_id: string;
  repo_id: string;
  name: string;
  dot: string;
  nodes: WorkflowGraphNode[];
  edges: WorkflowGraphEdge[];
  diagnostics: {
    error?: unknown;
    items?: WorkflowDiagnostic[];
  };
}

export interface ProjectConfig {
  default_environment?: string;
  allowed_execution_modes?: string[];
  environments?: Record<
    string,
    {
      mode?: string;
      description?: string;
      image?: string;
      working_dir?: string;
    }
  >;
  [key: string]: unknown;
}

export interface ProjectConfigStatus {
  repo_id: string;
  status: string;
  config: ProjectConfig;
}

export interface LaunchRunInput {
  repo_path: string;
  workflow_name?: string;
  workflow?: string;
  actor_label: string;
  inputs: Record<string, string>;
  requested_environment?: string;
}

export interface SerializedRunSpec {
  run_id?: string;
  repo_path?: string;
  workflow_name?: string;
  workflow?: string;
  actor_label?: string;
  inputs?: Record<string, string>;
  requested_environment?:
    | string
    | {
        mode?: string;
        name?: string;
        image?: string;
      };
  [key: string]: unknown;
}

export interface RunRecord {
  id: string;
  status: RunStatus;
  repo_id: string | null;
  workflow_id: string | null;
  run_spec: SerializedRunSpec | null;
  actor_label: string;
  source_commit?: string;
  source_branch?: string;
  worktree_path: string | null;
  managed_branch: string | null;
  error_category: string | null;
  error_message: string | null;
  created_at: string | null;
  updated_at: string | null;
  started_at: string | null;
  completed_at: string | null;
}

export interface RunEvent {
  sequence: number;
  event_type: string;
  payload: Record<string, unknown>;
  actor_label: string;
  created_at: string | null;
}

export interface ApprovalDecision {
  id: string;
  run_id: string;
  node_id: string | null;
  question: string;
  answer: string | null;
  actor_label: string;
  status: "pending" | "decided" | string;
  created_at: string | null;
  decided_at: string | null;
}

export interface ApprovalInput {
  answer: string;
  actor_label: string;
}

export interface ArtifactRecord {
  id: string | null;
  run_id: string | null;
  kind: string;
  name: string;
  uri: string;
  media_type: string;
  size_bytes: number;
  sha256: string;
  created_at: string | null;
}

export interface CheckpointRecord {
  id: string | null;
  run_id: string | null;
  node_id: string;
  stage_index: number;
  commit_sha: string;
  ref_name: string;
  created_at: string | null;
}

export interface WriteBackInput {
  target_branch: string;
  actor_label: string;
  overwrite?: boolean;
  allow_protected?: boolean;
}

export interface WriteBackRecord {
  id: string | null;
  run_id: string | null;
  source_branch: string;
  target_branch: string;
  actor_label: string;
  status: string;
  commit_sha: string | null;
  error_message: string | null;
  created_at: string | null;
  applied_at: string | null;
}

export interface FsBrowseEntry {
  name: string;
  path: string;
  kind: "directory" | "file" | string;
  is_git_repo: boolean;
}

export interface FsBrowseResult {
  path: string;
  roots: string[];
  items: FsBrowseEntry[];
  truncated: boolean;
}

export interface RunDiffFile {
  path: string;
  status: string;
  additions: number;
  deletions: number;
  patch?: string;
  patch_truncated?: boolean;
}

export interface RunDiff {
  run_id: string;
  base_commit: string;
  head_commit: string;
  truncated: boolean;
  files: RunDiffFile[];
}

export interface SystemHealth {
  status: string;
}

export interface SystemCapacity {
  active_runs: number;
  max_concurrent_runs: number | null;
  available_slots: number | null;
}

export interface SecretMetadata {
  name: string;
  configured: boolean;
  updated_at: string | null;
}

export interface SettingsVariable {
  key: string;
  value: string;
  updated_at: string | null;
}

export interface ModelCatalogRow {
  provider: string;
  model: string;
  display_name: string;
  context_window: number;
  max_output: number | null;
  supports_tools: boolean;
  supports_vision: boolean;
  supports_reasoning: boolean;
  is_default: boolean;
  is_small: boolean;
  source: "curated" | "provider" | string;
}

export interface ModelTestSummary {
  ok: number;
  failed: number;
  skipped: number;
  tested_at: string;
}

export interface ModelTestResult {
  provider: string;
  model: string;
  display_name: string;
  ok: boolean;
  latency_ms: number | null;
  error: string | null;
}

export interface ModelTestResponse {
  summary: ModelTestSummary;
  items: ModelTestResult[];
}

export interface ModelSyncSummary {
  synced: number;
  failed: number;
  skipped: number;
  synced_at: string;
}

export interface ModelSyncItem {
  provider: string;
  ok: boolean;
  models_synced: number;
  error: string | null;
}

export interface ModelSyncResponse {
  summary: ModelSyncSummary;
  items: ModelSyncItem[];
}

export type ModelSyncLimit = 5 | 10 | "all";

export type SettingsEditability = "editable" | "restart-required" | "read-only" | "reserved";

export interface SettingsPageRow {
  label: string;
  description: string;
  value: string | number | boolean | null;
  editability: SettingsEditability;
}

export interface SettingsPageGroup {
  title: string;
  rows: SettingsPageRow[];
}

export interface SettingsPage {
  id: string;
  title: string;
  description: string;
  groups: SettingsPageGroup[];
}

export interface SettingsOverview {
  models: {
    default_provider: string;
    default_model: string;
    provider_credentials: Record<
      string,
      {
        name: string;
        env_var: string;
        configured: boolean;
        updated_at: string | null;
        source: string;
      }
    >;
  };
  environments: {
    default: string;
    items: Array<{ name: string; mode: string; description: string }>;
  };
  variables: {
    items: SettingsVariable[];
  };
  server: {
    status: string;
    max_concurrent_runs: number | null;
  };
  storage: {
    status: string;
  };
  monitoring: {
    active_runs: number;
    event_stream: string;
  };
  pages: SettingsPage[];
}

interface ItemsResponse<T> {
  items: T[];
}

function apiUrl(path: string): string {
  return apiPath(path);
}

export function apiErrorMessage(data: unknown, status: number): string {
  if (data && typeof data === "object") {
    const record = data as Record<string, unknown>;
    const detail = record.detail;
    if (detail && typeof detail === "object") {
      const detailError = (detail as Record<string, unknown>).error;
      if (typeof detailError === "string" && detailError) {
        return detailError;
      }
    }
    if (typeof record.message === "string" && record.message) {
      return record.message;
    }
    if (typeof record.error === "string" && record.error) {
      return record.error;
    }
  }
  return `Request failed with ${status}`;
}

async function readJson<T>(response: Response): Promise<T> {
  const text = await response.text();
  const data = text ? JSON.parse(text) : null;
  if (!response.ok) {
    throw new Error(apiErrorMessage(data, response.status));
  }
  return data as T;
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(apiUrl(path), {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {})
    }
  });
  return readJson<T>(response);
}

export async function registerRepo(input: { name: string; local_path: string }): Promise<Repo> {
  return requestJson<Repo>("/api/repos", {
    method: "POST",
    body: JSON.stringify(input)
  });
}

export async function listRepos(): Promise<Repo[]> {
  const response = await requestJson<ItemsResponse<Repo>>("/api/repos");
  return response.items;
}

export async function getRepo(repoId: string): Promise<Repo> {
  return requestJson<Repo>(`/api/repos/${encodeURIComponent(repoId)}`);
}

export async function deleteRepo(repoId: string): Promise<{ deleted?: boolean }> {
  return requestJson<{ deleted?: boolean }>(`/api/repos/${encodeURIComponent(repoId)}`, {
    method: "DELETE"
  });
}

export async function refreshRepo(
  repoId: string,
  options: { force?: boolean } = {}
): Promise<RepoRefreshResult> {
  return requestJson<RepoRefreshResult>(`/api/repos/${encodeURIComponent(repoId)}/refresh`, {
    method: "POST",
    body: JSON.stringify({ force: options.force ?? true })
  });
}

export async function getProjectConfig(repoId: string): Promise<ProjectConfigStatus> {
  return requestJson<ProjectConfigStatus>(
    `/api/repos/${encodeURIComponent(repoId)}/project-config`
  );
}

export async function listWorkflows(repoId: string): Promise<Workflow[]> {
  return requestJson<Workflow[]>(`/api/repos/${encodeURIComponent(repoId)}/workflows`);
}

export async function findWorkflow(workflowId: string): Promise<{ repo: Repo; workflow: Workflow }> {
  const repos = await listRepos();
  for (const repo of repos) {
    const workflows = await listWorkflows(repo.id);
    const workflow = workflows.find((item) => item.id === workflowId);
    if (workflow) {
      return { repo, workflow };
    }
  }
  throw new Error(`Workflow ${workflowId} was not found`);
}

export async function validateWorkflow(workflowId: string): Promise<Workflow> {
  return requestJson<Workflow>(`/api/workflows/${encodeURIComponent(workflowId)}/validate`, {
    method: "POST",
    body: JSON.stringify({})
  });
}

export async function getWorkflowGraph(workflowId: string): Promise<WorkflowGraph> {
  return requestJson<WorkflowGraph>(`/api/workflows/${encodeURIComponent(workflowId)}/graph`);
}

export async function launchRun(input: LaunchRunInput): Promise<RunRecord> {
  return requestJson<RunRecord>("/api/runs", {
    method: "POST",
    body: JSON.stringify(input)
  });
}

export function runSpecToLaunchInput(runSpec: SerializedRunSpec | null): LaunchRunInput | null {
  if (!runSpec || typeof runSpec.repo_path !== "string") {
    return null;
  }
  const workflowName =
    typeof runSpec.workflow_name === "string" ? runSpec.workflow_name : runSpec.workflow;
  if (typeof workflowName !== "string") {
    return null;
  }
  const requestedEnvironment =
    typeof runSpec.requested_environment === "string"
      ? runSpec.requested_environment
      : runSpec.requested_environment?.name ?? runSpec.requested_environment?.mode ?? "";
  return {
    repo_path: runSpec.repo_path,
    workflow_name: workflowName,
    actor_label: typeof runSpec.actor_label === "string" ? runSpec.actor_label : "operator",
    inputs: runSpec.inputs && typeof runSpec.inputs === "object" ? runSpec.inputs : {},
    requested_environment: requestedEnvironment
  };
}

export async function listRuns(filters: {
  status?: string;
  repo_id?: string;
  workflow_id?: string;
  actor_label?: string;
} = {}): Promise<RunRecord[]> {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value) {
      params.set(key, value);
    }
  }
  const suffix = params.toString() ? `?${params.toString()}` : "";
  const response = await requestJson<ItemsResponse<RunRecord>>(`/api/runs${suffix}`);
  return response.items;
}

export async function getRun(runId: string): Promise<RunRecord> {
  return requestJson<RunRecord>(`/api/runs/${encodeURIComponent(runId)}`);
}

export async function cancelRun(runId: string): Promise<{ id: string; status: string }> {
  return requestJson<{ id: string; status: string }>(
    `/api/runs/${encodeURIComponent(runId)}/cancel`,
    {
      method: "POST",
      body: JSON.stringify({})
    }
  );
}

export async function getRunDiff(
  runId: string,
  options: { includePatch?: boolean } = {}
): Promise<RunDiff> {
  const params = new URLSearchParams();
  if (options.includePatch) {
    params.set("include_patch", "true");
  }
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return requestJson<RunDiff>(`/api/runs/${encodeURIComponent(runId)}/diff${suffix}`);
}

export async function browseFilesystem(
  path?: string,
  options: { mode?: "registration" | string } = {}
): Promise<FsBrowseResult> {
  const params = new URLSearchParams();
  if (path) {
    params.set("path", path);
  }
  if (options.mode) {
    params.set("mode", options.mode);
  }
  return requestJson<FsBrowseResult>(`/api/fs/browse?${params.toString()}`);
}

export async function listRunEvents(runId: string): Promise<RunEvent[]> {
  const response = await requestJson<ItemsResponse<RunEvent>>(
    `/api/runs/${encodeURIComponent(runId)}/events`
  );
  return response.items;
}

export async function listApprovals(runId: string): Promise<ApprovalDecision[]> {
  const response = await requestJson<ItemsResponse<ApprovalDecision>>(
    `/api/runs/${encodeURIComponent(runId)}/approvals`
  );
  return response.items;
}

export async function listArtifacts(runId: string): Promise<ArtifactRecord[]> {
  const response = await requestJson<ItemsResponse<ArtifactRecord>>(
    `/api/runs/${encodeURIComponent(runId)}/artifacts`
  );
  return response.items;
}

export function artifactUrl(runId: string, artifactId: string): string {
  return apiUrl(
    `/api/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(artifactId)}`
  );
}

export async function listCheckpoints(runId: string): Promise<CheckpointRecord[]> {
  const response = await requestJson<ItemsResponse<CheckpointRecord>>(
    `/api/runs/${encodeURIComponent(runId)}/checkpoints`
  );
  return response.items;
}

export async function answerApproval(
  runId: string,
  approvalId: string,
  input: ApprovalInput
): Promise<ApprovalDecision> {
  return requestJson<ApprovalDecision>(
    `/api/runs/${encodeURIComponent(runId)}/approvals/${encodeURIComponent(approvalId)}`,
    {
      method: "POST",
      body: JSON.stringify(input)
    }
  );
}

export async function promoteWriteBack(
  runId: string,
  input: WriteBackInput
): Promise<WriteBackRecord> {
  return requestJson<WriteBackRecord>(`/api/runs/${encodeURIComponent(runId)}/writeback`, {
    method: "POST",
    body: JSON.stringify(input)
  });
}

export async function getSystemHealth(): Promise<SystemHealth> {
  return requestJson<SystemHealth>("/api/system/health");
}

export async function getSystemCapacity(): Promise<SystemCapacity> {
  return requestJson<SystemCapacity>("/api/system/capacity");
}

export async function getSettings(): Promise<SettingsOverview> {
  return requestJson<SettingsOverview>("/api/settings");
}

export async function getModelCatalog(): Promise<ModelCatalogRow[]> {
  const response = await requestJson<ItemsResponse<ModelCatalogRow>>(
    "/api/settings/models/catalog"
  );
  return response.items;
}

export async function testModels(): Promise<ModelTestResponse> {
  return requestJson<ModelTestResponse>("/api/settings/models/test", {
    method: "POST",
    body: JSON.stringify({})
  });
}

export async function syncModels(limit: ModelSyncLimit = 10): Promise<ModelSyncResponse> {
  return requestJson<ModelSyncResponse>("/api/settings/models/sync", {
    method: "POST",
    body: JSON.stringify({ limit: limit === "all" ? null : limit })
  });
}

export async function listSettingsSecrets(): Promise<SecretMetadata[]> {
  const response = await requestJson<ItemsResponse<SecretMetadata>>("/api/settings/secrets");
  return response.items;
}

export async function putSettingsSecret(name: string, value: string): Promise<SecretMetadata> {
  return requestJson<SecretMetadata>(`/api/settings/secrets/${encodeURIComponent(name)}`, {
    method: "PUT",
    body: JSON.stringify({ value })
  });
}

export async function deleteSettingsSecret(name: string): Promise<SecretMetadata> {
  return requestJson<SecretMetadata>(`/api/settings/secrets/${encodeURIComponent(name)}`, {
    method: "DELETE"
  });
}

export async function listSettingsVariables(): Promise<SettingsVariable[]> {
  const response = await requestJson<ItemsResponse<SettingsVariable>>("/api/settings/variables");
  return response.items;
}

export async function putSettingsVariable(
  key: string,
  value: string
): Promise<SettingsVariable> {
  return requestJson<SettingsVariable>(`/api/settings/variables/${encodeURIComponent(key)}`, {
    method: "PUT",
    body: JSON.stringify({ value })
  });
}

export async function deleteSettingsVariable(key: string): Promise<{ key: string; deleted: boolean }> {
  return requestJson<{ key: string; deleted: boolean }>(
    `/api/settings/variables/${encodeURIComponent(key)}`,
    {
      method: "DELETE"
    }
  );
}

export function openRunEventSource(runId: string): EventSource {
  return new EventSource(apiUrl(`/api/runs/${encodeURIComponent(runId)}/events/stream`));
}

export const knownRunEventTypes = [
  "run.queued",
  "run.preparing",
  "run.started",
  "run.completed",
  "run.failed",
  "run.cancelled",
  "pipeline.started",
  "pipeline.completed",
  "pipeline.failed",
  "pipeline.event",
  "stage.started",
  "stage.completed",
  "stage.failed",
  "stage.retrying",
  "checkpoint.saved",
  "approval.requested",
  "approval.decided",
  "writeback.applied",
  "writeback.failed"
];
