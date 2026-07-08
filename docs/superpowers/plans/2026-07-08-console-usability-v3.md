# Console Usability V3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the 11 confirmed console usability/correctness issues without changing workflow execution semantics.

**Architecture:** Add small backend service helpers for repository re-indexing, filesystem browse roots, model catalog sync, path defaults, and timestamp normalization; keep route handlers thin and preserve existing API shapes where possible. Reuse current React routes/components and add narrow UI controls for refresh, folder picking, graph display, bounded run-detail sections, error formatting, model sync, and timestamp rendering.

**Tech Stack:** Python 3.12, Starlette, SQLAlchemy asyncio, SQLite/Postgres-compatible models, React 19, TypeScript, Vite, @hpcc-js/wasm Graphviz, pytest, ruff, pyright.

## Global Constraints

- Branch: `codex/console-usability-v3`.
- Docs-and-code plan only until review; do not implement before approval.
- Execution semantics must not change: no changes to pipeline scheduling, worktree run execution, approval behavior, write-back behavior, or handler execution.
- Guard against regressions in run list/board/detail, settings, themed/bounded graph, and existing catalog IDs.
- Provider sync and model testing must run with no keys in tests; live provider calls only when credentials are configured and operator explicitly clicks a sync/test action.
- Full gate after implementation: `uv run pytest tests/`, `uv run ruff check .`, `uv run pyright`, and `cd web && npm run build`.
- Reviewer visual gate: graph colors survive clicks/pans, run-detail long sections are bounded, invalid workflow shows real diagnostic, pre-run graph renders on workflow page, folder browser can pick an unregistered repo, timestamps are not in the future.

---

## Pinned Decisions

1. **Re-index trigger:** Use both manual refresh and auto refresh on repo detail load, with a cheap mtime gate by default. Rejected always-reindex on every repo/workflow API request because it turns ordinary reads into repeated filesystem parsing work.
2. **Re-index API shape:** Add `POST /api/repos/{repo_id}/refresh` returning the serialized repo plus `workflow_count`, `changed`, and `removed_workflow_count`. Rejected overloading `GET /api/repos/{repo_id}/workflows` because a GET should not mutate diagnostics/index rows.
3. **Storage defaults:** Resolve default worktree/artifact roots to user data (`$XDG_DATA_HOME/attractor` or `~/.local/share/attractor`) and Docker `/data` when that directory exists or `ATTRACTOR_RUNNING_IN_DOCKER` is truthy; explicit CLI flags/env vars still win. Rejected target-repo-relative storage because it pollutes registered repositories.
4. **Old storage dirs:** Do not auto-move existing `.attractor-worktrees` or `.attractor-artifacts`; warn/document and continue to honor explicit overrides. Rejected automatic migration because worktrees contain git metadata and moving them risks corruption.
5. **Catalog sync:** Keep curated metadata as baseline, merge synced provider IDs by `(provider, id)`, and mark API-discovered rows with `source="provider"` while preserving curated context/speed/capability fields when IDs overlap. Rejected replacing the curated list wholesale because provider list APIs do not consistently return context, tool, vision, reasoning, or cost metadata.
6. **Catalog sync trigger:** Operator clicks **Sync from provider** in Settings; no startup sync. Rejected sync-on-startup because it adds credentialed network calls and noisy failures to local server boot.
7. **Folder browser safety:** Introduce registration browse roots based on configured allowlist/env plus safe defaults (`Path.home()`, current working directory, and parents of already registered repos), with server-side path resolution and symlink escape checks. Rejected arbitrary absolute filesystem browsing.
8. **Timestamp format:** Store/create aware UTC datetimes and serialize every API timestamp as RFC 3339 UTC with `Z` (for example `2026-07-08T19:14:03.123456Z`). Rejected naive ISO strings because browsers parse them as local time and produce future-relative labels.
9. **Registration name field:** Persist the entered repo name because `RegisteredRepoModel.name` already exists and API registration already accepts `name`. Rejected removing the UI field because the backend model and repo list already use it.

## File Structure

- Modify `README.md`: document user-data storage defaults, explicit overrides, model sync behavior, and folder-browser allowed roots.
- Create `src/attractor_platform/indexing.py`: shared repo workflow re-index helper, mtime signature helper, stale workflow deletion selection.
- Create `src/attractor_platform/paths.py`: platform user-data directory and default worktree/artifact root resolution.
- Create `src/attractor_llm/catalog_sync.py`: provider model-list client interface, row merge logic, in-memory synced overlay.
- Modify `src/attractor_llm/catalog.py`: expose curated models separately, include source metadata, and support merged list lookups without breaking existing callers.
- Modify `src/attractor_llm/adapters/base.py`: add optional `list_models()` protocol method or standalone sync client type.
- Modify provider adapters in `src/attractor_llm/adapters/`: implement list-models HTTP calls for configured providers, isolated from completion APIs.
- Modify `src/attractor_platform/storage/repositories.py`: add repo update/re-index support, stale workflow deletion, and UTC timestamp normalization at write boundaries.
- Modify `src/attractor_platform/storage/models.py`: no schema changes expected; keep timezone columns.
- Modify `src/attractor_server/__main__.py`: use path default resolver for CLI defaults.
- Modify `src/attractor_server/platform_app.py`: add refresh endpoint, browse-root behavior, timestamp serializer, sync endpoint, richer error extraction.
- Modify `web/src/api.ts`: add repo refresh, model sync types/functions, richer API error extraction, timestamp assumptions.
- Modify `web/src/routes/RepoDetailRoute.tsx`: auto-refresh workflows on load and add manual Refresh action.
- Modify `web/src/routes/ReposRoute.tsx`: make server directory browser usable for registration and preserve entered repo name.
- Modify `web/src/routes/WorkflowDetailRoute.tsx`: render graph before any run and render invalid-workflow errors as strings.
- Modify `web/src/components/GraphViewer.tsx`: reapply highlights after transform changes and allow empty-event pre-run usage.
- Modify `web/src/routes/RunDetailRoute.tsx`: cap Branch Diff, Event Timeline, and Artifacts sections; fix checkpoint summary fallback.
- Modify `web/src/routes/SettingsRoute.tsx`: add **Sync from provider** action next to **Test models**.
- Modify `web/src/components/ui.tsx` and `web/src/runViewModel.ts`: harden timestamp parsing/formatting tests around offset/Z strings.
- Modify `web/src/styles.css`: add bounded scroll containers and folder browser styling only where needed.
- Tests: update/add `tests/test_phase3_console_api_contracts.py`, `tests/test_workflow_packages.py`, `tests/test_console_product_v2_catalog.py`, `tests/test_console_product_v2_model_testing.py`, `tests/test_platform_config.py`, `tests/test_phase2_storage.py`, `web/src/graphHighlight.test.ts`, `web/src/settingsRouteRender.test.tsx`, `web/src/runViewModel.test.ts`.

### Task 1: Repo Re-Index Backend

**Files:**
- Create: `src/attractor_platform/indexing.py`
- Modify: `src/attractor_platform/storage/repositories.py`
- Modify: `src/attractor_server/platform_app.py`
- Test: `tests/test_phase3_console_api_contracts.py`
- Test: `tests/test_workflow_packages.py`

**Interfaces:**
- Produces: `WorkflowIndexResult(repo, packages, changed: bool, removed_workflow_count: int)` and `async reindex_registered_repo(services, repo, force: bool)`.
- Produces repository methods `update_repo_index_metadata(...)` and `delete_workflows_not_in(repo_id: str, workflow_ids: set[str]) -> int`.
- Consumes existing `discover_workflow_packages()`, `_workflow_identifier()`, `_serialize_diagnostics()`, `read_git_metadata()`.

- [ ] **Step 1: Write failing backend tests**

Add tests that register a repo, add a new workflow after registration, call `POST /api/repos/{repo_id}/refresh`, and assert the new workflow appears. Add a second test that fixes an invalid `workflow.dot`, refreshes, and asserts stale diagnostics are cleared. Add a third test that deletes a workflow directory and asserts stale DB workflow rows are removed.

Run: `uv run pytest tests/test_phase3_console_api_contracts.py -k "refresh or reindex" -v`
Expected: FAIL because `/api/repos/{repo_id}/refresh` does not exist.

- [ ] **Step 2: Implement shared re-index helper**

Create `src/attractor_platform/indexing.py` with a small pure helper for workflow tree mtime and an async orchestrator that:

```python
@dataclass(frozen=True)
class WorkflowIndexResult:
    repo: Any
    packages: list[WorkflowPackage]
    changed: bool
    removed_workflow_count: int

def workflow_tree_signature(repo_path: str | Path) -> int:
    root = Path(repo_path).expanduser().resolve() / ".attractor" / "workflows"
    if not root.exists():
        return 0
    return max((int(path.stat().st_mtime_ns) for path in root.rglob("*")), default=0)
```

Keep platform-app-specific serialization in `platform_app.py`; the helper should not import Starlette.

- [ ] **Step 3: Add repository deletion/update methods**

In `PlatformRepository`, add:

```python
async def delete_workflows_not_in(self, repo_id: str, workflow_ids: set[str]) -> int:
    async with session_scope(self._session_factory) as session:
        current = await session.scalars(
            select(WorkflowPackageModel.id).where(WorkflowPackageModel.repo_id == repo_id)
        )
        stale_ids = [workflow_id for workflow_id in current if workflow_id not in workflow_ids]
        for workflow_id in stale_ids:
            workflow = await session.get(WorkflowPackageModel, workflow_id)
            if workflow is not None:
                await session.delete(workflow)
        return len(stale_ids)
```

Also add a focused repo metadata update method so refresh can update branch/commit/dirty state and `last_indexed_at` without forcing a registration rename.

- [ ] **Step 4: Add refresh endpoint**

In `platform_app.py`, add `refresh_repo(request)` and route `POST /api/repos/{repo_id}/refresh`. The endpoint should load the repo, re-read git metadata, rediscover packages, upsert every package with fresh diagnostics, delete stale workflow rows, update `last_indexed_at`, and return:

```json
{
  "repo": { "...": "serialized repo" },
  "workflow_count": 3,
  "removed_workflow_count": 1,
  "changed": true
}
```

- [ ] **Step 5: Run targeted tests**

Run: `uv run pytest tests/test_phase3_console_api_contracts.py tests/test_workflow_packages.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/attractor_platform/indexing.py src/attractor_platform/storage/repositories.py src/attractor_server/platform_app.py tests/test_phase3_console_api_contracts.py tests/test_workflow_packages.py
git commit -m "fix: add repo workflow reindex endpoint"
```

### Task 2: UTC Timestamp Correctness

**Files:**
- Modify: `src/attractor_server/platform_app.py`
- Modify: `src/attractor_platform/storage/repositories.py`
- Modify: `src/attractor_platform/executor.py`
- Modify: `web/src/components/ui.tsx`
- Modify: `web/src/runViewModel.test.ts`
- Test: `tests/test_phase2_storage.py`
- Test: `tests/test_phase3_console_api_contracts.py`

**Interfaces:**
- Produces: `_utc_now() -> dt.datetime`, `_normalize_utc(timestamp) -> dt.datetime`, `_serialize_timestamp(timestamp) -> str | None`.
- Consumes existing ORM timestamp fields and frontend `formatDate`, `formatRelativeTime`, `formatDuration`.

- [ ] **Step 1: Write failing timestamp tests**

Add API tests that insert/return naive and aware datetimes and assert serialized values end with `Z`. Add frontend tests for `formatRelativeTime("2026-07-03T12:00:00Z")` and `formatDate()` to verify they do not treat UTC values as local future times.

Run: `uv run pytest tests/test_phase2_storage.py tests/test_phase3_console_api_contracts.py -k "timestamp or utc" -v && cd web && npm run test:run-view-model`
Expected: FAIL for naive ISO serialization or missing `Z`.

- [ ] **Step 2: Normalize backend timestamp creation**

Replace local `dt.datetime.now(dt.UTC)` calls in platform write paths with `_utc_now()` or a shared local helper. At repository boundaries, normalize any incoming timestamp:

```python
def _normalize_utc(timestamp: dt.datetime) -> dt.datetime:
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=dt.UTC)
    return timestamp.astimezone(dt.UTC)
```

- [ ] **Step 3: Serialize explicit UTC**

Update `_serialize_timestamp()` and `_serialize_settings_timestamp()`:

```python
def _serialize_timestamp(timestamp: dt.datetime | None) -> str | None:
    if timestamp is None:
        return None
    normalized = _normalize_utc(timestamp)
    return normalized.isoformat().replace("+00:00", "Z")
```

- [ ] **Step 4: Fix checkpoint summary fallback**

In `RunDetailRoute.eventSummary`, change `checkpoint.saved` so missing `commit_sha` does not print `at None`:

```ts
case "checkpoint.saved":
  if (node && commit !== "None") return `Checkpoint saved for ${node} at ${commit}`;
  if (node) return `Checkpoint saved for ${node}`;
  return commit !== "None" ? `Checkpoint saved ${commit}` : "Checkpoint saved";
```

- [ ] **Step 5: Run targeted tests**

Run: `uv run pytest tests/test_phase2_storage.py tests/test_phase3_console_api_contracts.py -k "timestamp or event or checkpoint" -v && cd web && npm run test:run-view-model`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/attractor_server/platform_app.py src/attractor_platform/storage/repositories.py src/attractor_platform/executor.py web/src/components/ui.tsx web/src/runViewModel.test.ts tests/test_phase2_storage.py tests/test_phase3_console_api_contracts.py
git commit -m "fix: serialize platform timestamps as utc"
```

### Task 3: Invalid Workflow Error Rendering

**Files:**
- Modify: `web/src/api.ts`
- Modify: `web/src/routes/WorkflowDetailRoute.tsx`
- Test: `web/src/settingsRouteRender.test.tsx`

**Interfaces:**
- Produces: `apiErrorMessage(data: unknown, status: number): string`.
- Consumes backend error objects shaped like `{code, message, detail}` and workflow diagnostics shaped like `{error, items}`.

- [ ] **Step 1: Write failing render test**

Add a mini-DOM route test for `/workflows/<id>` where validation returns:

```json
{"code":"workflow_package_error","message":"Unable to parse workflow.dot","detail":{"error":"Parse error: Line 21, col 16: Unexpected character '\"'"}}
```

Assert rendered markup includes `Parse error: Line 21, col 16` and does not include `Route unavailable`.

- [ ] **Step 2: Harden API error extraction**

In `readJson`, replace object-to-string behavior with:

```ts
function apiErrorMessage(data: unknown, status: number): string {
  if (data && typeof data === "object") {
    const record = data as Record<string, unknown>;
    const detail = record.detail;
    if (detail && typeof detail === "object") {
      const detailError = (detail as Record<string, unknown>).error;
      if (typeof detailError === "string" && detailError) return detailError;
    }
    if (typeof record.message === "string" && record.message) return record.message;
    if (typeof record.error === "string" && record.error) return record.error;
  }
  return `Request failed with ${status}`;
}
```

- [ ] **Step 3: Render workflow diagnostics as strings**

In `Diagnostics`, add a formatter that accepts `unknown`:

```ts
function diagnosticErrorText(error: unknown): string | null {
  if (!error) return null;
  if (typeof error === "string") return error;
  if (typeof error === "object") {
    const record = error as Record<string, unknown>;
    const detail = record.detail;
    if (detail && typeof detail === "object" && typeof (detail as Record<string, unknown>).error === "string") {
      return (detail as Record<string, unknown>).error as string;
    }
    if (typeof record.message === "string") return record.message;
  }
  return String(error);
}
```

- [ ] **Step 4: Run frontend tests**

Run: `cd web && npm run test:settings-render && npm run build`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/api.ts web/src/routes/WorkflowDetailRoute.tsx web/src/settingsRouteRender.test.tsx
git commit -m "fix: render invalid workflow diagnostics"
```

### Task 4: Model Catalog Provider Sync

**Files:**
- Create: `src/attractor_llm/catalog_sync.py`
- Modify: `src/attractor_llm/catalog.py`
- Modify: `src/attractor_llm/adapters/base.py`
- Modify: `src/attractor_llm/adapters/anthropic.py`
- Modify: `src/attractor_llm/adapters/openai.py`
- Modify: `src/attractor_llm/adapters/gemini.py`
- Modify: `src/attractor_server/platform_app.py`
- Modify: `web/src/api.ts`
- Modify: `web/src/routes/SettingsRoute.tsx`
- Test: `tests/test_console_product_v2_catalog.py`
- Test: `tests/test_console_product_v2_model_testing.py`
- Test: `web/src/settingsRouteRender.test.tsx`

**Interfaces:**
- Produces: `SyncedModelInfo`, `sync_provider_models(provider, api_key)`, `merge_model_catalog(curated, synced)`.
- Produces endpoint `POST /api/settings/models/sync`.
- Consumes `_configured_provider_api_keys()` and existing model test redaction.

- [ ] **Step 1: Write failing sync tests**

Add tests with fake syncer returning `gpt-live-new` for OpenAI and a curated overlap for `gpt-5.5`. Assert catalog response includes the new row, overlap keeps curated metadata, and missing keys skip without network calls.

Run: `uv run pytest tests/test_console_product_v2_catalog.py tests/test_console_product_v2_model_testing.py -k "sync or catalog" -v`
Expected: FAIL because sync endpoint and overlay do not exist.

- [ ] **Step 2: Add catalog merge model**

Keep `MODEL_CATALOG` as curated baseline. Add in-memory synced overlay keyed by provider/id. `list_models(provider)` should return curated rows plus synced rows, sorted with curated ranking first and provider rows after.

- [ ] **Step 3: Implement provider list-models clients**

Use existing HTTP configuration patterns in each adapter, but keep list calls separate from completions. Expected provider calls:

```text
OpenAI: GET /v1/models
Anthropic: GET /v1/models with anthropic-version header
Gemini: GET /v1beta/models
```

Map only stable fields available from APIs: provider, id, display_name. Leave unknown metadata as conservative defaults unless a curated row overlaps.

- [ ] **Step 4: Add server endpoint**

`POST /api/settings/models/sync` should iterate configured provider keys, call the syncer, redact errors, update overlay, and return:

```json
{"summary":{"synced":4,"failed":0,"skipped":8,"synced_at":"...Z"},"items":[...]}
```

- [ ] **Step 5: Add Settings UI action**

In Settings Models page, add a **Sync from provider** secondary button near **Test models**. Show a compact summary and then refresh catalog rows.

- [ ] **Step 6: Run targeted tests**

Run: `uv run pytest tests/test_console_product_v2_catalog.py tests/test_console_product_v2_model_testing.py -v && cd web && npm run test:settings-render`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/attractor_llm/catalog.py src/attractor_llm/catalog_sync.py src/attractor_llm/adapters/base.py src/attractor_llm/adapters/anthropic.py src/attractor_llm/adapters/openai.py src/attractor_llm/adapters/gemini.py src/attractor_server/platform_app.py web/src/api.ts web/src/routes/SettingsRoute.tsx tests/test_console_product_v2_catalog.py tests/test_console_product_v2_model_testing.py web/src/settingsRouteRender.test.tsx
git commit -m "feat: sync model catalog from providers"
```

### Task 5: User Data Storage Defaults

**Files:**
- Create: `src/attractor_platform/paths.py`
- Modify: `src/attractor_server/__main__.py`
- Modify: `README.md`
- Test: `tests/test_platform_config.py`

**Interfaces:**
- Produces: `default_platform_data_dir()`, `default_worktree_root()`, `default_artifact_root()`, `resolve_platform_roots(worktree_arg, artifact_arg)`.
- Consumes explicit CLI args/env vars exactly as today when supplied.

- [ ] **Step 1: Write failing path tests**

Test that defaults resolve outside `Path.cwd()`, explicit values are honored, `XDG_DATA_HOME` is honored, and Docker mode returns `/data/attractor/worktrees` and `/data/attractor/artifacts`.

- [ ] **Step 2: Add path resolver**

Implement:

```python
def default_platform_data_dir() -> Path:
    if os.environ.get("ATTRACTOR_RUNNING_IN_DOCKER") or Path("/data").is_dir():
        return Path("/data/attractor")
    xdg = os.environ.get("XDG_DATA_HOME", "").strip()
    return (Path(xdg) if xdg else Path.home() / ".local" / "share") / "attractor"
```

- [ ] **Step 3: Wire CLI defaults**

Change argparse defaults to `None`; after parsing, resolve env/default roots so explicit `--worktree-root`, `--artifact-root`, `ATTRACTOR_WORKTREE_ROOT`, and `ATTRACTOR_ARTIFACT_ROOT` still win.

- [ ] **Step 4: Document behavior**

Update README configuration defaults and include a note: old CWD-relative `.attractor-*` directories are not migrated automatically; pass explicit flags to keep using them.

- [ ] **Step 5: Run targeted tests**

Run: `uv run pytest tests/test_platform_config.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/attractor_platform/paths.py src/attractor_server/__main__.py README.md tests/test_platform_config.py
git commit -m "fix: default platform storage to user data"
```

### Task 6: Graph Viewer Pre-Run Graph and Persistent Highlights

**Files:**
- Modify: `web/src/components/GraphViewer.tsx`
- Modify: `web/src/routes/WorkflowDetailRoute.tsx`
- Modify: `web/src/graphHighlight.test.ts`
- Test: `tests/test_phase3_graph_api.py`

**Interfaces:**
- Produces: reusable `<GraphViewer workflowId={workflowId} events={[]} />` on workflow detail.
- Consumes existing `getWorkflowGraph()` endpoint.

- [ ] **Step 1: Write failing frontend graph tests**

Add a graph-controller test that simulates applying highlights, then applying a transform update, and asserts highlight classes remain after reapplication. Add a render test for workflow detail that asserts graph panel markup appears before launch.

- [ ] **Step 2: Reapply highlights after transform changes**

In `GraphViewer`, extend the layout effect dependency:

```ts
useLayoutEffect(() => {
  if (!graphSceneRef.current || !svgMarkup) return;
  applyGraphHighlightsToRenderedSvg(graphSceneRef.current, highlightState);
}, [highlightState, svgMarkup, graphTransform.scale, graphTransform.x, graphTransform.y]);
```

- [ ] **Step 3: Render pre-run graph**

In `WorkflowDetailRoute`, insert `<GraphViewer workflowId={workflowId} events={[]} />` after Validation and before Launch Run. Keep it visible for invalid workflows so parse diagnostics and graph errors surface in place.

- [ ] **Step 4: Run targeted tests**

Run: `uv run pytest tests/test_phase3_graph_api.py -v && cd web && npm run test:graph`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/components/GraphViewer.tsx web/src/routes/WorkflowDetailRoute.tsx web/src/graphHighlight.test.ts tests/test_phase3_graph_api.py
git commit -m "fix: keep graph highlights and show pre-run graph"
```

### Task 7: Bounded Run Detail Sections

**Files:**
- Modify: `web/src/routes/RunDetailRoute.tsx`
- Modify: `web/src/styles.css`
- Test: `web/src/settingsRouteRender.test.tsx`

**Interfaces:**
- Produces CSS utility `.bounded-section-scroll` or section-specific classes.
- Consumes existing `BranchDiffPanel`, `EventTimeline`, and `ArtifactTable`.

- [ ] **Step 1: Write failing render/style test**

Add a route render test that builds a run with many events/artifacts/diff files and asserts `run-detail-scroll` wrappers exist around Branch Diff, Event Timeline, and Artifacts.

- [ ] **Step 2: Add bounded wrappers**

Wrap the relevant panel contents:

```tsx
<Panel title="Event Timeline">
  <div className="run-detail-scroll run-detail-scroll-events">
    <EventTimeline events={events} loading={relatedState.loading} />
  </div>
</Panel>
```

Repeat for Branch Diff and Artifacts. Do not wrap Checkpoints unless visual review requests it.

- [ ] **Step 3: Add CSS**

```css
.run-detail-scroll {
  max-height: min(32rem, 58vh);
  overflow: auto;
  padding-right: var(--space-0-5);
}

.run-detail-scroll-diff {
  max-height: min(34rem, 62vh);
}
```

- [ ] **Step 4: Run frontend tests/build**

Run: `cd web && npm run test:settings-render && npm run build`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/routes/RunDetailRoute.tsx web/src/styles.css web/src/settingsRouteRender.test.tsx
git commit -m "fix: bound long run detail sections"
```

### Task 8: Registration Folder Browser and Repo Name

**Files:**
- Modify: `src/attractor_server/platform_app.py`
- Modify: `web/src/api.ts`
- Modify: `web/src/routes/ReposRoute.tsx`
- Modify: `README.md`
- Test: `tests/test_phase3_console_api_contracts.py`
- Test: `web/src/settingsRouteRender.test.tsx`

**Interfaces:**
- Produces browse response with `roots` when path is omitted or `/api/fs/browse?mode=registration`.
- Produces persisted registration name through existing `register_repo` path.
- Consumes `_browse_allowed_roots()` for registered repo browsing.

- [ ] **Step 1: Write failing browse/name tests**

Backend: with no repos registered, browse a temp root made available through `ATTRACTOR_BROWSE_ROOTS` and assert directories are listed. Register repo with `name="Custom Name"` and assert list/detail returns that name after refresh and launch paths.

Frontend: render Repos route, assert browser input hint does not say only registered paths, and clicking Use preserves the typed name unless name is empty.

- [ ] **Step 2: Add registration browse roots**

Add `_registration_browse_roots()`:

```python
def _registration_browse_roots() -> list[Path]:
    configured = os.environ.get("ATTRACTOR_BROWSE_ROOTS", "")
    roots = [Path(item).expanduser().resolve() for item in configured.split(os.pathsep) if item]
    roots.extend([Path.cwd().resolve(), Path.home().resolve()])
    return unique_existing_dirs(roots)
```

For `/api/fs/browse`, allow `mode=registration` or no registered roots to browse within these roots while retaining symlink escape and hidden-path filters.

- [ ] **Step 3: Fix frontend browser flow**

Default the first Browse action to the server-provided roots or home/current root, change input hint copy, add an Up button when parent remains allowed, and set `name` from the selected git repo only when the name field is empty.

- [ ] **Step 4: Preserve custom repo names**

Audit `register_repo`, `DurableRunExecutor.register_and_launch`, and refresh code. Registration should persist the submitted `name`; auto-registration during CLI/run launch may continue to use folder name because there is no operator-entered name in that path.

- [ ] **Step 5: Run targeted tests**

Run: `uv run pytest tests/test_phase3_console_api_contracts.py -k "browse or name or repo" -v && cd web && npm run test:settings-render`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/attractor_server/platform_app.py web/src/api.ts web/src/routes/ReposRoute.tsx README.md tests/test_phase3_console_api_contracts.py web/src/settingsRouteRender.test.tsx
git commit -m "fix: support server-side repo folder picking"
```

### Task 9: Repo Detail Auto Refresh UI

**Files:**
- Modify: `web/src/api.ts`
- Modify: `web/src/routes/RepoDetailRoute.tsx`
- Modify: `web/src/styles.css`
- Test: `web/src/settingsRouteRender.test.tsx`

**Interfaces:**
- Produces: `refreshRepo(repoId: string): Promise<RepoRefreshResult>`.
- Consumes Task 1 refresh endpoint.

- [ ] **Step 1: Write failing UI test**

Add a route render test for `/repos/<id>` that asserts `POST /api/repos/<id>/refresh` is called once on initial load and again when clicking Refresh.

- [ ] **Step 2: Add API client**

In `api.ts`:

```ts
export interface RepoRefreshResult {
  repo: Repo;
  workflow_count: number;
  removed_workflow_count: number;
  changed: boolean;
}

export async function refreshRepo(repoId: string): Promise<RepoRefreshResult> {
  return requestJson<RepoRefreshResult>(`/api/repos/${encodeURIComponent(repoId)}/refresh`, {
    method: "POST",
    body: JSON.stringify({})
  });
}
```

- [ ] **Step 3: Wire route behavior**

In `RepoDetailRoute`, call `refreshRepo(repoId)` in an effect, then refresh repo/workflow states. Add panel action button **Refresh** with loading and result notice.

- [ ] **Step 4: Run frontend tests/build**

Run: `cd web && npm run test:settings-render && npm run build`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/api.ts web/src/routes/RepoDetailRoute.tsx web/src/styles.css web/src/settingsRouteRender.test.tsx
git commit -m "feat: refresh repo index from console"
```

## Final Verification

- [ ] Run Python tests: `uv run pytest tests/`
- [ ] Run lint: `uv run ruff check .`
- [ ] Run type check: `uv run pyright`
- [ ] Run web build: `cd web && npm run build`
- [ ] Run focused web tests: `cd web && npm run test:graph && npm run test:settings-render && npm run test:run-view-model && npm run test:app-base`
- [ ] Start backend and frontend for manual review:

```bash
uv run python -m attractor_server --platform --port 8000
cd web && npm run dev
```

- [ ] Manually verify: graph colors survive click/pan, run detail page height is bounded, invalid workflow diagnostic renders inline, workflow page graph renders pre-run, folder browser can select an unregistered repo, and timestamps show past/now correctly.

## Self-Review

- **Spec coverage:** Covered all groups: re-index (#2/#9), registration UX (#1/#3), graph viewer (#4/#6), run-detail length (#7), invalid error display (#8), storage location (#5), catalog sync (#10), timestamps (#11).
- **Priority order:** Tasks follow requested priority order: 1, 8, 5, 7, 6, 3, 4, 2, with a small UI follow-up for repo auto-refresh after backend refresh exists.
- **Red-flag scan:** No temporary-marker or copy-forward language remains. Each task has concrete files, interfaces, test commands, and expected results.
- **Type consistency:** New API names are consistent across backend and frontend: `refreshRepo`, `RepoRefreshResult`, `WorkflowIndexResult`, `sync_provider_models`, and UTC timestamp helpers.
- **Rejected alternatives:** Key decisions include rejected alternatives for re-index trigger, storage migration, catalog sync strategy, browse safety, timestamp format, and name-field handling.
